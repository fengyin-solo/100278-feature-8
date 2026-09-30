"""工班管理接口：维护工班，覆盖开始当班、完成交班、下班休班、临时调配等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.shift import STATUS_ORDER, ShiftService

router = APIRouter(prefix="/api/shift", tags=["工班管理"])

service = ShiftService()

LIST_FIELDS = ["工班编号", "工班名称", "当班组长", "作业线数", "出勤人数", "作业时段", "作业效率", "工班状态"]
STATUSES = STATUS_ORDER


@router.get("/board", response_model=dict)
def board() -> dict[str, Any]:
    """工班看板：当班工班数、出勤总人数、作业线数只统计「当班中」工班。"""
    return service.board_stats()


@router.get("/ledger", response_model=list[dict])
def ledger(
    keyword: str | None = Query(default=None, description="按工班编号或名称检索"),
    reviewed: bool | None = Query(default=None, description="true=已复核，false=待复核"),
) -> list[dict]:
    """工班台账：交班后自动落一份到待复核清单。"""
    return service.list_ledger(reviewed=reviewed, keyword=keyword)


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按工班编号检索"),
    status: str | None = Query(default=None, description="待交班、当班中、已交班、已休班"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按工班编号与状态过滤工班管理列表；没有数据时返回空页，不报错。"""
    if status and status not in STATUSES:
        raise HTTPException(status_code=400, detail=f"工班状态只支持：{'、'.join(STATUSES)}")
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条工班明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"工班 {entry_id} 不存在或已归档")
    return entry


@router.get("/{entry_id}/history", response_model=list[dict])
def get_history(entry_id: int) -> list[dict]:
    """读取工班的状态变更与调配登记记录（每次变更含作业时段与组长）。"""
    if service.get_entry(entry_id) is None:
        raise HTTPException(status_code=404, detail=f"工班 {entry_id} 不存在或已归档")
    return service.list_history(entry_id)


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条工班，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="工班已登记", entry=entry)


@router.patch("/{entry_id}", response_model=ActionResult)
def update_entry(entry_id: int, payload: EntryPayload) -> ActionResult:
    """当班过程中更新出勤人数、作业线数等作业字段，保证交班时资料是新的。"""
    entry, message = service.update_entry(entry_id, payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条工班执行开始当班、完成交班、下班休班、临时调配；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    extra = {key: value for key, value in payload.values.items() if key != "action"}
    entry, message = service.run_action(entry_id, action, extra)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/ledger/{record_id}/review", response_model=ActionResult)
def review_ledger(record_id: int) -> ActionResult:
    """复核台账记录：从待复核清单划掉，但记录仍保留在台账里。"""
    for row in service.list_ledger():
        if int(row.get("id", 0)) == record_id:
            row["已复核"] = True
            row["复核状态"] = "已复核"
            row["pending"] = False
            return ActionResult(ok=True, message="台账记录已复核", entry=row)
    raise HTTPException(status_code=404, detail=f"台账记录 {record_id} 不存在")


@router.get("/export/all")
def export_entries() -> dict[str, Any]:
    """导出工班管理清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "shift", "total": total, "items": items}
