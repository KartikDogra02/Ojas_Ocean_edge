import re
from collections import Counter, defaultdict

from fastapi import APIRouter

from app.auth import CurrentPrincipal
from app.db import get_db
from app.models.expense_claim import ExpenseStatus
from app.models.work_order import WorkOrderStatus
from app.models.work_plan import Priority, WorkPlanStatus
from app.models.workflow import (
    ChainCertificate,
    ChainCrew,
    ChainExpenses,
    ChainFsr,
    ChainPlan,
    ChainWorkOrder,
    PipelineStage,
    Workflow,
    WorkflowChain,
    WorkflowSummary,
)
from app.routers.work_plans import engineers_by_id, plan_visibility

router = APIRouter(prefix="/workflow", tags=["workflow"])


def _plan_status(plan: dict) -> WorkPlanStatus:
    if plan.get("work_order"):
        return WorkPlanStatus.CONVERTED
    return WorkPlanStatus.ASSIGNED if plan["assigned_engineer_ids"] else WorkPlanStatus.DRAFT


def _stage(order: dict | None, has_fsr: bool, has_cert: bool) -> PipelineStage:
    if has_cert:
        return PipelineStage.CERTIFIED
    if has_fsr:
        return PipelineStage.REPORTED
    if order and order["status"] == WorkOrderStatus.IN_PROGRESS.value:
        return PipelineStage.IN_PROGRESS
    if order:
        return PipelineStage.DISPATCHED
    return PipelineStage.STAGED


@router.get("", response_model=Workflow)
async def workflow(
    principal: CurrentPrincipal,
    search: str | None = None,
    stage: PipelineStage | None = None,
    priority: Priority | None = None,
    skip: int = 0,
    limit: int = 100,
):
    """Every job traced from Work Plan → Work Order → Crew → FSR → ISO Certificate, with expenses.

    `search` matches plan, work order or FSR numbers, the customer or the title. The summary counts every job you
    can see, regardless of the filters. Service engineers only see jobs they're on.
    """
    db = get_db()
    visible = await plan_visibility(principal)
    plans = [p async for p in db.work_plans.find(visible)]
    orders = {o["_id"]: o async for o in db.work_orders.find(visible)}
    order_ids = list(orders)
    fsrs = {
        f["work_order"]["id"]: f async for f in db.field_service_reports.find({"work_order.id": {"$in": order_ids}})
    }
    certs: dict = defaultdict(list)
    async for c in db.certificates.find({"work_order.id": {"$in": order_ids}}).sort("created_at", 1):
        certs[c["work_order"]["id"]].append(c)
    expenses: dict = defaultdict(lambda: ChainExpenses())
    async for claim in db.expense_claims.find(
        {"work_plan": {"$ne": None}, "status": {"$ne": ExpenseStatus.REJECTED.value}},
        {"work_plan.plan_number": 1, "amount_cents": 1},
    ):
        e = expenses[claim["work_plan"]["plan_number"]]
        e.count += 1
        e.total = round(e.total + claim["amount_cents"] / 100, 2)

    # One chain per work plan (with its work order, if converted), plus one per work order created directly.
    pairs = [(p, orders.get(p["work_order"]["id"]) if p.get("work_order") else None) for p in plans]
    pairs += [(None, o) for o in orders.values() if not o.get("work_plan")]
    engineers = await engineers_by_id(
        {e for plan, order in pairs for e in (order or plan)["assigned_engineer_ids"]}
    )

    chains: list[WorkflowChain] = []
    for plan, order in pairs:
        source = order or plan
        fsr = fsrs.get(order["_id"]) if order else None
        cert_docs = certs.get(order["_id"], []) if order else []
        crew_ids = source["assigned_engineer_ids"]
        steps = [
            True,  # a plan exists, or the work order was created directly (no plan step)
            order is not None,
            order is not None and bool(crew_ids),
            fsr is not None,
            bool(cert_docs),
        ]
        chains.append(
            WorkflowChain(
                title=source["title"],
                priority=source["priority"],
                customer=source["customer"]["company"],
                service_type=order["service_type"] if order else None,
                equipment=order.get("equipment") if order else None,
                stage=_stage(order, fsr is not None, bool(cert_docs)),
                completion=round(100 * sum(steps) / len(steps)),
                plan=ChainPlan(
                    id=str(plan["_id"]),
                    plan_number=plan["plan_number"],
                    status=_plan_status(plan),
                    estimated_duration_days=plan.get("estimated_duration_days"),
                    created_at=plan["created_at"],
                )
                if plan
                else None,
                work_order=ChainWorkOrder(
                    id=str(order["_id"]),
                    work_order_number=order["work_order_number"],
                    status=order["status"],
                    service_type=order["service_type"],
                    site_address=order["customer"].get("site_address"),
                    created_at=order["created_at"],
                )
                if order
                else None,
                crew=ChainCrew(
                    lead_engineer_id=order.get("lead_engineer_id") if order else None,
                    engineers=[engineers[e] for e in crew_ids if e in engineers],
                ),
                fsr=ChainFsr(
                    id=str(fsr["_id"]),
                    fsr_number=fsr["fsr_number"],
                    customer_rep_name=fsr["customer_rep_name"],
                    customer_satisfaction=fsr["customer_satisfaction"],
                    spare_parts_count=len(fsr["spare_parts"]),
                    parts_total=fsr["parts_total_cents"] / 100,
                    submitted_at=fsr["submitted_at"],
                )
                if fsr
                else None,
                certificates=[
                    ChainCertificate(
                        id=str(c["_id"]),
                        certificate_number=c["certificate_number"],
                        result=c["result"],
                        calibration_date=c["calibration_date"].date(),
                    )
                    for c in cert_docs
                ],
                expenses=expenses[plan["plan_number"]] if plan else ChainExpenses(),
            )
        )

    counts = Counter(c.stage for c in chains)
    summary = WorkflowSummary(
        total_chains=len(chains),
        staged_plans=counts[PipelineStage.STAGED],
        work_orders_dispatched=counts[PipelineStage.DISPATCHED],
        field_ops_in_progress=counts[PipelineStage.IN_PROGRESS],
        reported=counts[PipelineStage.REPORTED],
        iso_certified=counts[PipelineStage.CERTIFIED],
    )

    if stage is not None:
        chains = [c for c in chains if c.stage == stage]
    if priority is not None:
        chains = [c for c in chains if c.priority == priority]
    if search:
        needle = re.compile(re.escape(search.strip()), re.IGNORECASE)
        chains = [
            c
            for c in chains
            if any(
                needle.search(text)
                for text in (
                    c.title,
                    c.customer,
                    c.plan.plan_number if c.plan else "",
                    c.work_order.work_order_number if c.work_order else "",
                    c.fsr.fsr_number if c.fsr else "",
                )
            )
        ]
    # Newest first, by whichever step was created first.
    chains.sort(key=lambda c: (c.plan or c.work_order).created_at, reverse=True)
    return Workflow(summary=summary, chains=chains[skip : skip + limit])
