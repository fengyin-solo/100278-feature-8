"""工班管理业务规则：状态流转、字段校验、看板口径与交班台账都收在这里。

状态只能按 待交班 → 当班中 → 已交班 → 已休班 依次推进：
- 开始当班：待交班 → 当班中（同一工班同一天只能有一条当班记录）；
- 完成交班：当班中 → 已交班（作业线数、出勤人数缺失不允许交班），并在工班台账落一份待复核；
- 临时调配：不推进状态，先登记作业时段与组长再回到当班中，每次变更记入调配履历；
- 结束休班：已交班 → 已休班，已休班为终态，不允许退回。
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from app.store import store

MODULE = "shift"
REQUIRED_FIELDS = ["工班编号", "工班名称", "当班组长"]
OPTIONAL_FIELDS = ["作业线数", "出勤人数", "作业时段", "作业效率"]
NUMERIC_FIELDS = ["作业线数", "出勤人数"]

STATUS_PENDING = "待交班"
STATUS_ON_DUTY = "当班中"
STATUS_HANDED = "已交班"
STATUS_RESTED = "已休班"
STATUS_ORDER = [STATUS_PENDING, STATUS_ON_DUTY, STATUS_HANDED, STATUS_RESTED]
# 已实际开班的状态：用于“同一工班同一天只能有一条当班记录”的查重。
OPENED_STATUSES = {STATUS_ON_DUTY, STATUS_HANDED, STATUS_RESTED}

ACTION_START = "开始当班"
ACTION_HANDOVER = "完成交班"
ACTION_REASSIGN = "临时调配"
ACTION_REST = "结束休班"

# 每个动作只允许从指定状态触发，不允许跳级，也不允许从终态退回。
ACTION_FROM: dict[str, set[str]] = {
    ACTION_START: {STATUS_PENDING},
    ACTION_HANDOVER: {STATUS_ON_DUTY},
    ACTION_REASSIGN: {STATUS_ON_DUTY},
    ACTION_REST: {STATUS_HANDED},
}
# 临时调配登记后回到当班中，不推进状态；其余动作各推进一步。
ACTION_TARGET = {
    ACTION_START: STATUS_ON_DUTY,
    ACTION_HANDOVER: STATUS_HANDED,
    ACTION_REST: STATUS_RESTED,
}
ACTION_LABELS = {
    STATUS_PENDING: ACTION_START,
    STATUS_ON_DUTY: f"{ACTION_HANDOVER} / {ACTION_REASSIGN}",
    STATUS_HANDED: ACTION_REST,
    STATUS_RESTED: "（已闭环）",
}

LEDGER_REVIEW_PENDING = "待复核"
LEDGER_REVIEW_DONE = "已复核"


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _text(values: dict[str, Any], key: str) -> str:
    return str(values.get(key) or "").strip()


def _to_int(value: Any) -> int | None:
    """把表单里的人数/线数解析成非负整数；空值或非法值返回 None。"""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        number = int(float(text))
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def _duty_date(entry: dict[str, Any], values: dict[str, Any]) -> str:
    """当班日期优先取提交值，再取记录值，最后退回作业时段前 10 位或当天。"""
    raw = _text(values, "当班日期") or str(entry.get("当班日期") or "").strip()
    if not raw:
        period = _text(values, "作业时段") or str(entry.get("作业时段") or "").strip()
        raw = period[:10] if period else date.today().isoformat()
    return raw[:10]


class ShiftService:
    def __init__(self) -> None:
        # 工班台账：交班记录的待复核清单，独立于 store 的模块表，不进运营概览统计。
        self._ledger: list[dict[str, Any]] = []
        self._seed_ledger()

    # ---------- 工班台账 ----------

    def _seed_ledger(self) -> None:
        for row in store.rows(MODULE):
            status = row.get("status")
            if status == STATUS_HANDED:
                self._append_ledger(row, reviewed=False)
            elif status == STATUS_RESTED:
                record = self._append_ledger(row, reviewed=True)
                record["复核人"] = "值班调度"
                record["复核时间"] = _now_text()

    def _append_ledger(self, entry: dict[str, Any], *, reviewed: bool) -> dict[str, Any]:
        record = {
            "id": max((int(item.get("id", 0)) for item in self._ledger), default=0) + 1,
            "工班记录id": entry.get("id"),
            "工班编号": entry.get("工班编号", ""),
            "工班名称": entry.get("工班名称", ""),
            "当班组长": entry.get("当班组长", ""),
            "当班日期": entry.get("当班日期") or _duty_date(entry, {}),
            "作业时段": entry.get("作业时段", ""),
            "作业线数": _to_int(entry.get("作业线数")),
            "出勤人数": _to_int(entry.get("出勤人数")),
            "交班时间": _now_text(),
            "复核状态": LEDGER_REVIEW_DONE if reviewed else LEDGER_REVIEW_PENDING,
            "复核人": None,
            "复核时间": None,
        }
        self._ledger.append(record)
        return record

    def list_ledger(self, review_status: str | None = None) -> list[dict[str, Any]]:
        rows = self._ledger
        if review_status:
            rows = [row for row in rows if row.get("复核状态") == review_status]
        return list(reversed(rows))

    def review_ledger(
        self, ledger_id: int, reviewer: str
    ) -> tuple[dict[str, Any] | None, str]:
        record = next((item for item in self._ledger if int(item.get("id", 0)) == ledger_id), None)
        if record is None:
            return None, f"台账记录 {ledger_id} 不存在或已归档"
        if record.get("复核状态") == LEDGER_REVIEW_DONE:
            return None, "该交班记录已复核，无需重复操作"
        reviewer = reviewer.strip()
        if not reviewer:
            return None, "请填写复核人后再提交复核"
        record["复核状态"] = LEDGER_REVIEW_DONE
        record["复核人"] = reviewer
        record["复核时间"] = _now_text()
        return record, "交班记录已复核"

    # ---------- 工班看板 ----------

    def board(self) -> dict[str, Any]:
        """看板只统计当班中的工班；交班后即剔除，避免半夜还挂着白班数据。"""
        on_duty = [row for row in store.rows(MODULE) if row.get("status") == STATUS_ON_DUTY]
        return {
            "items": [
                {"label": "当班工班数", "value": len(on_duty)},
                {"label": "出勤总人数", "value": sum(_to_int(row.get("出勤人数")) or 0 for row in on_duty)},
                {"label": "完成作业线", "value": sum(_to_int(row.get("作业线数")) or 0 for row in on_duty)},
            ],
            "待复核": sum(1 for item in self._ledger if item.get("复核状态") == LEDGER_REVIEW_PENDING),
        }

    # ---------- 工班记录 ----------

    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("工班编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not _text(values, field)]
        if missing:
            return None, missing
        updates, errors = self._parse_updates(values)
        if errors:
            return None, errors
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: _text(values, field) for field in REQUIRED_FIELDS})
        entry.update(updates)
        entry["status"] = STATUS_ORDER[0]
        entry["工班状态"] = STATUS_ORDER[0]
        entry["当班日期"] = None
        entry["调配记录"] = []
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def _parse_updates(self, values: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
        """解析可更新字段：人数/线数必须为正整数，文本字段去空白；空值视为不更新。"""
        updates: dict[str, Any] = {}
        errors: list[str] = []
        for field in ("作业时段", "作业效率"):
            text = _text(values, field)
            if text:
                updates[field] = text
        for field in NUMERIC_FIELDS:
            if field not in values or not str(values.get(field) or "").strip():
                continue
            number = _to_int(values.get(field))
            if number is None or number <= 0:
                errors.append(f"{field}需为正整数")
            else:
                updates[field] = number
        return updates, errors

    def run_action(
        self,
        entry_id: int,
        action: str,
        values: dict[str, Any] | None = None,
        remark: str | None = None,
    ) -> tuple[dict[str, Any] | None, str]:
        values = values or {}
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"工班 {entry_id} 不存在或已归档"
        if action not in ACTION_FROM:
            return None, f"动作「{action}」不属于工班管理可执行范围"

        current = str(entry.get("status") or "")
        if current not in ACTION_FROM[action]:
            if current == STATUS_RESTED:
                return None, "工班已休班，状态不能退回；如需重新开班请登记新工班"
            allowed = ACTION_LABELS.get(current, "")
            return None, (
                f"工班当前为{current}，不能执行「{action}」；状态只能按"
                f"{'→'.join(STATUS_ORDER)}依次推进，不允许跳级。当前可执行：{allowed}"
            )

        if action == ACTION_START:
            return self._start(entry, values)
        if action == ACTION_HANDOVER:
            return self._handover(entry)
        if action == ACTION_REASSIGN:
            return self._reassign(entry, values, remark)
        return self._rest(entry)

    def _start(
        self, entry: dict[str, Any], values: dict[str, Any]
    ) -> tuple[dict[str, Any], str]:
        duty_date = _duty_date(entry, values)
        duplicate = next(
            (
                row for row in store.rows(MODULE)
                if int(row.get("id", 0)) != int(entry.get("id", 0))
                and str(row.get("工班编号") or "") == str(entry.get("工班编号") or "")
                and str(row.get("当班日期") or "") == duty_date
                and row.get("status") in OPENED_STATUSES
            ),
            None,
        )
        if duplicate is not None:
            return None, (
                f"工班{entry.get('工班编号')}在{duty_date}已有一条{duplicate.get('status')}记录，"
                "同一工班同一天不能出现两条当班记录"
            )

        updates, errors = self._parse_updates(values)
        if errors:
            return None, "、".join(errors)
        entry.update(updates)
        entry["当班日期"] = duty_date
        entry["status"] = STATUS_ON_DUTY
        entry["工班状态"] = STATUS_ON_DUTY
        entry["pending"] = True
        return entry, f"工班已于 {duty_date} 开始当班"

    def _handover(self, entry: dict[str, Any]) -> tuple[dict[str, Any], str]:
        missing = [
            field for field in NUMERIC_FIELDS
            if (v := _to_int(entry.get(field))) is None or v <= 0
        ]
        if missing:
            return None, f"{'、'.join(missing)}缺失或不是正整数，补齐后才允许交班"
        record = self._append_ledger(entry, reviewed=False)
        entry["status"] = STATUS_HANDED
        entry["工班状态"] = STATUS_HANDED
        entry["pending"] = True
        return entry, f"工班已完成交班，台账待复核清单新增 1 条（台账编号 {record['id']}）"

    def _reassign(
        self, entry: dict[str, Any], values: dict[str, Any], remark: str | None
    ) -> tuple[dict[str, Any], str]:
        period = _text(values, "作业时段")
        leader = _text(values, "组长") or _text(values, "当班组长")
        missing = [name for name, value in (("作业时段", period), ("组长", leader)) if not value]
        if missing:
            return None, f"临时调配需先登记{'、'.join(missing)}，登记后才能回到当班中"

        updates, errors = self._parse_updates(values)
        if errors:
            return None, "、".join(errors)
        entry.update(updates)
        entry["作业时段"] = period
        entry["当班组长"] = leader
        entry.setdefault("调配记录", []).append({
            "时间": _now_text(),
            "作业时段": period,
            "组长": leader,
            "作业线数": _to_int(entry.get("作业线数")),
            "出勤人数": _to_int(entry.get("出勤人数")),
            "说明": str(remark or values.get("说明") or "").strip(),
        })
        # 临时调配不推进状态，登记后回到当班中。
        entry["status"] = STATUS_ON_DUTY
        entry["工班状态"] = STATUS_ON_DUTY
        return entry, "临时调配已登记，工班回到当班中"

    def _rest(self, entry: dict[str, Any]) -> tuple[dict[str, Any], str]:
        entry["status"] = STATUS_RESTED
        entry["工班状态"] = STATUS_RESTED
        entry["pending"] = False
        return entry, "工班已休班，本轮状态闭环"
