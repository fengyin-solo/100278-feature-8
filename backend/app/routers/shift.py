"""工班管理接口：维护工班，覆盖开始当班、完成交班、临时调配、结束休班等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.shift import LEDGER_REVIEW_PENDING, ShiftService

router = APIRouter(prefix="/api/shift", tags=["工班管理"])

service = ShiftService()

LIST_FIELDS = ["工班编号", "工班名称", "当班组长", "作业线数", "出勤人数", "作业时段", "作业效率", "工班状态"]
STATUSES = ["待交班", "当班中", "已交班", "已休班"]


class ReviewPayload(BaseModel):
    """台账复核提交。"""

    复核人: str = Field(default="")


@router.get("/board")
def shift_board() -> dict[str, Any]:
    """工班看板：当班人数、作业线数只统计当班中的工班，交班后立即变化。"""
    return service.board()


@router.get("/ledger")
def list_ledger(
    review_status: str | None = Query(default=None, description="待复核、已复核"),
) -> dict[str, Any]:
    """工班台账：交班后落到这里的待复核清单，最新一条在前。"""
    items = service.list_ledger(review_status=review_status)
    return {
        "module": "shift-ledger",
        "total": len(items),
        "pending": sum(1 for item in items if item.get("复核状态") == LEDGER_REVIEW_PENDING),
        "items": items,
    }


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出工班管理清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "shift", "total": total, "items": items}


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按工班编号检索"),
    status: str | None = Query(default=None, description="待交班、当班中、已交班、已休班"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按工班编号与状态过滤工班管理列表；没有数据时返回空页，不报错。"""
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


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条工班，缺字段时说明原因而不是静默丢弃。"""
    entry, errors = service.create_entry(payload.values)
    if entry is None:
        return ActionResult(ok=False, message=f"登记未通过：{'、'.join(errors)}")
    return ActionResult(ok=True, message="工班已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条工班执行状态动作；跳级、退回、缺字段都会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action, payload.values, payload.remark)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/ledger/{ledger_id}/review", response_model=ActionResult)
def review_ledger(ledger_id: int, payload: ReviewPayload) -> ActionResult:
    """复核台账里的交班记录；复核人不能为空。"""
    record, message = service.review_ledger(ledger_id, payload.复核人)
    if record is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=record)
