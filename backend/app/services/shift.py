"""工班管理业务规则：状态流转、字段校验、交班台账与看板口径都收在这里。

状态只能沿 待交班 → 当班中 → 已交班 → 已休班 单向推进：
- 待交班：登记后、开始当班前；开始当班时校验同工班同一天不得有第二条当班记录；
- 当班中：可更新出勤人数/作业线数，可登记临时调配（记作业时段与组长），资料齐了才能交班；
- 已交班：自动在工班台账落一份待复核记录，之后只能下班休班；
- 已休班：终态，不允许任何回退动作。
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any

from app.store import store

MODULE = "shift"
LEDGER_MODULE = "shift_ledger"
REQUIRED_FIELDS = ["工班编号", "工班名称", "当班组长"]
# 可在当班过程中维护的作业字段
EDITABLE_FIELDS = ["作业线数", "出勤人数", "作业时段", "作业效率", "当班组长"]
STATUS_ORDER = ["待交班", "当班中", "已交班", "已休班"]
# 每个动作允许的起始状态与目标状态；不在表里的（原路）动作不允许发起
ACTION_RULES: dict[str, dict[str, str]] = {
    "开始当班": {"from": "待交班", "to": "当班中"},
    "完成交班": {"from": "当班中", "to": "已交班"},
    "下班休班": {"from": "已交班", "to": "已休班"},
}
# 临时调配不推进状态，但必须先登记（作业时段、组长）再回到当班中
DISPATCH_ACTION = "临时调配"
DISPATCH_FIELDS = ["作业时段", "组长"]
# 交班时必须为正整数的作业字段
HANDOVER_NUMBER_FIELDS = ["出勤人数", "作业线数"]
_DATE_PREFIX = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})")


def _positive_int(value: Any) -> int | None:
    """把出勤人数、作业线数解析成正整数；空值、小数、非数字一律视为不合格。"""
    if value is None:
        return None
    text = str(value).strip()
    if not text or not text.isdigit():
        return None
    number = int(text)
    return number if number > 0 else None


def duty_date(period: Any, fallback: date | None = None) -> str:
    """从作业时段开头取日期（兼容「2026-09-30 白班」这类写法）；取不到用今天。"""
    matched = _DATE_PREFIX.search(str(period or ""))
    if matched:
        year, month, day = (int(part) for part in matched.groups())
        try:
            return date(year, month, day).isoformat()
        except ValueError:
            pass
    return (fallback or date.today()).isoformat()


class ShiftService:
    # ------------------------------------------------------------------ 查询
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

    def list_history(self, entry_id: int) -> list[dict[str, Any]]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return []
        return list(entry.get("变更记录", []))

    def list_ledger(
        self,
        *,
        reviewed: bool | None = None,
        keyword: str | None = None,
    ) -> list[dict[str, Any]]:
        """工班台账：交班后自动落待复核记录，复核状态可筛选。"""
        rows = store.table(LEDGER_MODULE)
        if reviewed is not None:
            rows = [row for row in rows if bool(row.get("已复核")) == reviewed]
        if keyword:
            rows = [
                row
                for row in rows
                if keyword in str(row.get("工班编号", "")) or keyword in str(row.get("工班名称", ""))
            ]
        return rows

    def board_stats(self) -> dict[str, Any]:
        """看板口径：只统计「当班中」工班，交班后数字自然清零，不会再沿用白班数据。"""
        rows = [row for row in store.rows(MODULE) if row.get("status") == "当班中"]
        attendance = sum(_positive_int(row.get("出勤人数")) or 0 for row in rows)
        lines = sum(_positive_int(row.get("作业线数")) or 0 for row in rows)
        return {"当班工班数": len(rows), "出勤总人数": attendance, "完成作业线": lines}

    # ------------------------------------------------------------------ 登记
    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": store.next_id(MODULE)}
        entry.update({field: str(values.get(field)).strip() for field in REQUIRED_FIELDS})
        for field in ("作业线数", "出勤人数", "作业时段", "作业效率"):
            text = str(values.get(field) or "").strip()
            if text:
                entry[field] = text
        entry["status"] = STATUS_ORDER[0]
        entry["工班状态"] = STATUS_ORDER[0]
        entry["当班日期"] = duty_date(entry.get("作业时段"))
        entry["pending"] = True
        entry["abnormal"] = False
        entry["变更记录"] = []
        rows.append(entry)
        return entry, []

    def update_entry(
        self, entry_id: int, values: dict[str, Any]
    ) -> tuple[dict[str, Any] | None, str]:
        """当班过程中维护作业字段（出勤人数、作业线数等）；已休班记录封档不可改。"""
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"工班 {entry_id} 不存在或已归档"
        if entry["status"] == "已休班":
            return None, "工班已休班封档，作业资料不能再修改"
        changes: dict[str, str] = {}
        for field in EDITABLE_FIELDS:
            if field not in values:
                continue
            text = str(values.get(field) or "").strip()
            if field in HANDOVER_NUMBER_FIELDS and text and _positive_int(text) is None:
                return None, f"{field}必须是大于 0 的整数"
            if text and text != str(entry.get(field, "")):
                changes[field] = text
        if not changes:
            return entry, "工班资料没有变化"
        entry.update(changes)
        if "作业时段" in changes:
            entry["当班日期"] = duty_date(changes["作业时段"], date.fromisoformat(entry["当班日期"]))
        self._append_history(entry, "更新资料", changes.get("作业时段"), changes.get("当班组长"), note="、".join(changes))
        return entry, f"工班资料已更新：{'、'.join(changes)}"

    # ------------------------------------------------------------------ 流转
    def run_action(
        self, entry_id: int, action: str, values: dict[str, Any] | None = None
    ) -> tuple[dict[str, Any] | None, str]:
        values = values or {}
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"工班 {entry_id} 不存在或已归档"

        if action == DISPATCH_ACTION:
            return self._dispatch(entry, values)

        rule = ACTION_RULES.get(action)
        if rule is None:
            return None, f"动作「{action}」不属于工班管理可执行范围"

        current = entry["status"]
        if current == "已休班":
            return None, "工班已休班，状态不能回退"
        if current != rule["from"]:
            return None, self._flow_message(current, action, rule["to"])

        if action == "开始当班":
            message = self._ensure_unique_duty(entry)
            if message:
                return None, message
        elif action == "完成交班":
            missing = [
                field
                for field in HANDOVER_NUMBER_FIELDS
                if _positive_int(entry.get(field)) is None
            ]
            if missing:
                return None, f"出勤人数或作业线数未登记，不允许交班（缺：{'、'.join(missing)}）"

        target = rule["to"]
        entry["status"] = target
        entry["工班状态"] = target
        entry["pending"] = target != "已休班"
        self._append_history(entry, action, values.get("作业时段"), values.get("组长"))

        if action == "完成交班":
            self._create_ledger_entry(entry)
            return entry, "工班已交班，台账待复核清单已新增一条记录"
        return entry, f"工班已{action}"

    # ------------------------------------------------------------------ 内部
    def _dispatch(self, entry: dict[str, Any], values: dict[str, Any]) -> tuple[dict[str, Any], str]:
        """临时调配：必须先登记作业时段与组长，登记后仍处于当班中（不推进状态）。"""
        if entry["status"] != "当班中":
            return None, "只有当班中的工班可以登记临时调配"
        missing = [field for field in DISPATCH_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, f"临时调配需先登记：{'、'.join(missing)}"
        period = str(values["作业时段"]).strip()
        leader = str(values["组长"]).strip()
        self._append_history(entry, DISPATCH_ACTION, period, leader, note=values.get("备注"))
        return entry, f"临时调配已登记（{period} / 组长：{leader}），工班回到当班中"

    def _ensure_unique_duty(self, entry: dict[str, Any]) -> str | None:
        """同工班同一天只能有一条当班记录（当班中、已交班、已休班都占位）。"""
        duty_day = duty_date(entry.get("作业时段"), date.fromisoformat(entry["当班日期"]))
        entry["当班日期"] = duty_day
        for row in store.rows(MODULE):
            if row is entry:
                continue
            if str(row.get("工班编号", "")).strip() != str(entry["工班编号"]).strip():
                continue
            if row.get("当班日期") != duty_day:
                continue
            if row.get("status") in ("当班中", "已交班", "已休班"):
                return f"工班 {entry['工班编号']} 在 {duty_day} 已有一条当班记录，不能重复开始当班"
        return None

    @staticmethod
    def _flow_message(current: str, action: str, target: str) -> str:
        current_index = STATUS_ORDER.index(current)
        target_index = STATUS_ORDER.index(target)
        if target_index <= current_index:
            return f"工班当前为{current}，不能通过「{action}」回退到{target}"
        return f"工班当前为{current}，需先完成{STATUS_ORDER[current_index + 1]}前的手续，不能跳到{target}"

    @staticmethod
    def _append_history(
        entry: dict[str, Any],
        action: str,
        period: Any = None,
        leader: Any = None,
        note: Any = None,
    ) -> None:
        """每一次变更都记下时间、作业时段与组长，组长缺省取当班组长。"""
        record: dict[str, Any] = {
            "动作": action,
            "时间": date.today().isoformat(),
            "作业时段": str(period or entry.get("作业时段") or "").strip(),
            "组长": str(leader or entry.get("当班组长") or "").strip(),
            "变更后状态": entry.get("status"),
        }
        text_note = str(note or "").strip()
        if text_note:
            record["备注"] = text_note
        entry.setdefault("变更记录", []).append(record)

    def _create_ledger_entry(self, entry: dict[str, Any]) -> dict[str, Any]:
        """交班后在工班台账待复核清单落一份。"""
        ledger = store.rows(LEDGER_MODULE)
        record = {
            "id": store.next_id(LEDGER_MODULE),
            "工班id": entry["id"],
            "工班编号": entry.get("工班编号"),
            "工班名称": entry.get("工班名称"),
            "当班日期": entry.get("当班日期"),
            "作业时段": entry.get("作业时段"),
            "当班组长": entry.get("当班组长"),
            "出勤人数": _positive_int(entry.get("出勤人数")),
            "作业线数": _positive_int(entry.get("作业线数")),
            "交班时间": date.today().isoformat(),
            "复核状态": "待复核",
            "已复核": False,
            "pending": True,
        }
        ledger.append(record)
        return record
