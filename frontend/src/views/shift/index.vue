<template>
  <section class="page" data-module="shift">
    <header class="page-head">
      <div>
        <h2>工班管理</h2>
        <p class="page-desc">工班状态按 待交班 → 当班中 → 已交班 → 已休班 推进；看板人数随交班记录实时变化，交班记录自动进入台账待复核。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记工班</button>
        <button class="btn" type="button" @click="exportRows">导出工班清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>工班编号</span>
        <input v-model="keyword" placeholder="按工班编号检索" />
      </label>
      <label class="filter-item">
        <span>工班状态</span>
        <select v-model="statusFilter">
          <option value="">全部</option>
          <option v-for="s in statuses" :key="s" :value="s">{{ s }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ formatCell(row, column) }}</td>
          <td class="row-actions">
            <template v-if="actionsFor(row.status).length">
              <button
                v-for="action in actionsFor(row.status)"
                :key="action"
                class="link"
                type="button"
                @click="triggerAction(action, row)"
              >
                {{ action }}
              </button>
            </template>
            <button v-if="historyOf(row).length" class="link" type="button" @click="openHistory(row)">
              调配履历
            </button>
            <span v-if="!actionsFor(row.status).length && !historyOf(row).length" class="muted-text">已闭环</span>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无工班数据，可先登记工班</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条工班记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <section class="ledger-block">
      <div class="ledger-head">
        <h3>工班台账 · 待复核清单</h3>
        <label class="filter-item inline">
          <span>复核状态</span>
          <select v-model="ledgerFilter" @change="reloadLedger">
            <option value="">全部</option>
            <option value="待复核">待复核</option>
            <option value="已复核">已复核</option>
          </select>
        </label>
      </div>
      <table class="data-table">
        <thead>
          <tr>
            <th v-for="column in ledgerColumns" :key="column">{{ column }}</th>
            <th>复核</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in ledgerRows" :key="String(item.id)">
            <td v-for="column in ledgerColumns" :key="column">{{ item[column] ?? '—' }}</td>
            <td>
              <template v-if="item['复核状态'] === '待复核'">
                <input v-model="reviewers[Number(item.id)]" placeholder="复核人" class="review-input" />
                <button class="link" type="button" @click="reviewLedger(item)">提交复核</button>
              </template>
              <span v-else class="muted-text">已由 {{ item['复核人'] }} 复核</span>
            </td>
          </tr>
          <tr v-if="!ledgerRows.length">
            <td :colspan="ledgerColumns.length + 1" class="empty-state">暂无台账记录，工班完成交班后会自动落到这里</td>
          </tr>
        </tbody>
      </table>
    </section>

    <!-- 表单动作弹窗：开始当班 / 临时调配 / 登记工班 -->
    <div v-if="dialog.title" class="modal-mask" @click.self="closeDialog">
      <div class="modal-card">
        <h3 class="modal-title">{{ dialog.title }}</h3>
        <p class="modal-tip">{{ dialog.tip }}</p>
        <div v-for="field in dialog.fields" :key="field.key" class="modal-field">
          <label>
            <span>{{ field.label }}{{ field.required ? ' *' : '' }}</span>
            <input
              v-model="dialog.form[field.key]"
              :type="field.type === 'number' ? 'number' : 'text'"
              :placeholder="field.placeholder ?? ''"
            />
          </label>
        </div>
        <div class="modal-actions">
          <button class="btn ghost" type="button" @click="closeDialog">取消</button>
          <button class="btn primary" type="button" :disabled="dialog.saving" @click="submitDialog">
            {{ dialog.saving ? '提交中…' : '确认' }}
          </button>
        </div>
        <p v-if="dialog.error" class="error-text">{{ dialog.error }}</p>
      </div>
    </div>

    <!-- 调配履历弹窗 -->
    <div v-if="historyEntry" class="modal-mask" @click.self="historyEntry = null">
      <div class="modal-card">
        <h3 class="modal-title">调配履历 · {{ historyEntry['工班编号'] }}</h3>
        <table class="data-table">
          <thead>
            <tr><th>时间</th><th>作业时段</th><th>组长</th><th>作业线数</th><th>出勤人数</th><th>说明</th></tr>
          </thead>
          <tbody>
            <tr v-for="(log, idx) in historyOf(historyEntry)" :key="idx">
              <td>{{ log['时间'] }}</td>
              <td>{{ log['作业时段'] }}</td>
              <td>{{ log['组长'] }}</td>
              <td>{{ log['作业线数'] ?? '—' }}</td>
              <td>{{ log['出勤人数'] ?? '—' }}</td>
              <td>{{ log['说明'] || '—' }}</td>
            </tr>
          </tbody>
        </table>
        <div class="modal-actions">
          <button class="btn" type="button" @click="historyEntry = null">关闭</button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>
type Log = Record<string, string | number | null>
type StatItem = { label: string; value: number }
type DialogField = { key: string; label: string; required?: boolean; type?: 'text' | 'number'; placeholder?: string }
type DialogState = {
  title: string
  tip: string
  entryId: number | null
  fields: DialogField[]
  form: Record<string, string>
  saving: boolean
  error: string
  mode: 'action' | 'create'
}

const ENDPOINT = '/api/shift'
const columns = ["工班编号", "工班名称", "当班组长", "当班日期", "作业线数", "出勤人数", "作业时段", "作业效率", "status"]
const ledgerColumns = ["id", "工班编号", "工班名称", "当班组长", "当班日期", "作业时段", "作业线数", "出勤人数", "交班时间", "复核状态"]
const statuses = ["待交班", "当班中", "已交班", "已休班"]

// 状态只能依次推进，按钮按当前状态放行：已休班不再给任何动作。
const ACTION_MAP: Record<string, string[]> = {
  '待交班': ['开始当班'],
  '当班中': ['完成交班', '临时调配'],
  '已交班': ['结束休班'],
  '已休班': [],
}

const rows = ref<Row[]>([])
const total = ref(0)
const stats = ref<StatItem[]>([
  { label: '当班工班数', value: 0 },
  { label: '出勤总人数', value: 0 },
  { label: '完成作业线', value: 0 },
])
const errorMessage = ref('')
const keyword = ref('')
const statusFilter = ref('')

const ledgerRows = ref<Row[]>([])
const ledgerFilter = ref('待复核')
const reviewers = reactive<Record<number, string>>({})

const historyEntry = ref<Row | null>(null)

const dialog = reactive<DialogState>({
  title: '',
  tip: '',
  entryId: null,
  fields: [],
  form: {},
  saving: false,
  error: '',
  mode: 'action',
})

function actionsFor(status: string | number | null): string[] {
  return ACTION_MAP[String(status ?? '')] ?? []
}

function historyOf(row: Row): Log[] {
  const value = (row as unknown as { 调配记录?: Log[] }).调配记录
  return Array.isArray(value) ? value : []
}

function formatCell(row: Row, column: string): string | number | null {
  if (column === 'status') return String(row.status ?? '—')
  const value = row[column]
  return value === null || value === undefined || value === '' ? '—' : value
}

function resetFilters() {
  keyword.value = ''
  statusFilter.value = ''
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function makeDialog(title: string, tip: string, fields: DialogField[], mode: 'action' | 'create', entryId: number | null) {
  dialog.title = title
  dialog.tip = tip
  dialog.fields = fields
  dialog.entryId = entryId
  dialog.mode = mode
  dialog.error = ''
  dialog.saving = false
  dialog.form = {}
}

function closeDialog() {
  if (dialog.saving) return
  dialog.title = ''
  dialog.entryId = null
}

function openCreate() {
  makeDialog(
    '登记工班',
    '登记后状态为待交班；作业线数、出勤人数可在开始当班或临时调配时补齐。',
    [
      { key: '工班编号', label: '工班编号', required: true, placeholder: '如 SHIF-A' },
      { key: '工班名称', label: '工班名称', required: true, placeholder: '如 白班A组' },
      { key: '当班组长', label: '当班组长', required: true },
      { key: '作业时段', label: '作业时段', placeholder: '如 08:00-20:00' },
      { key: '作业线数', label: '作业线数', type: 'number', placeholder: '正整数' },
      { key: '出勤人数', label: '出勤人数', type: 'number', placeholder: '正整数' },
    ],
    'create',
    null,
  )
}

function triggerAction(action: string, row: Row) {
  if (action === '开始当班') {
    makeDialog(
      action,
      '同一工班同一天只能有一条当班记录；如不填当班日期，默认取作业时段或今天。可顺便补齐作业线数与出勤人数。',
      [
        { key: '当班日期', label: '当班日期', placeholder: 'YYYY-MM-DD，默认今天' },
        { key: '作业时段', label: '作业时段', placeholder: '如 20:00-08:00' },
        { key: '作业线数', label: '作业线数', type: 'number', placeholder: '正整数' },
        { key: '出勤人数', label: '出勤人数', type: 'number', placeholder: '正整数' },
      ],
      'action',
      Number(row.id),
    )
    return
  }
  if (action === '临时调配') {
    makeDialog(
      action,
      '临时调配先登记作业时段与组长，确认后回到当班中；每次变更都会记入调配履历，可同步更新人数与线数。',
      [
        { key: '作业时段', label: '作业时段', required: true, placeholder: '如 22:00-06:00' },
        { key: '组长', label: '组长', required: true },
        { key: '作业线数', label: '新作业线数', type: 'number', placeholder: '正整数' },
        { key: '出勤人数', label: '新出勤人数', type: 'number', placeholder: '正整数' },
        { key: '说明', label: '调配说明', placeholder: '如 2号泊位加开一条线' },
      ],
      'action',
      Number(row.id),
    )
    return
  }
  const tip = action === '完成交班'
    ? '交班后看板不再统计该工班，并在台账生成一条待复核记录，确认继续？'
    : '休班后本轮状态闭环且不能退回，确认继续？'
  if (!window.confirm(tip)) return
  void runAction(String(row.id), action)
}

async function submitDialog() {
  dialog.error = ''
  const missing = dialog.fields
    .filter((field) => field.required && !dialog.form[field.key]?.trim())
    .map((field) => field.label)
  if (missing.length) {
    dialog.error = `请填写：${missing.join('、')}`
    return
  }
  dialog.saving = true
  try {
    if (dialog.mode === 'create') {
      const result = await postJson(ENDPOINT, { values: dialog.form })
      if (!result.ok) {
        dialog.error = result.message
        return
      }
    } else if (dialog.entryId !== null) {
      const result = await postJson(`${ENDPOINT}/${dialog.entryId}/actions`, {
        values: { ...dialog.form, action: dialog.title },
        remark: dialog.form['说明'] || null,
      })
      if (!result.ok) {
        dialog.error = result.message
        return
      }
    }
    dialog.title = ''
    dialog.entryId = null
    await refresh()
  } catch (error) {
    dialog.error = error instanceof Error ? error.message : '提交失败'
  } finally {
    dialog.saving = false
  }
}

async function runAction(entryId: string, action: string) {
  errorMessage.value = ''
  try {
    const result = await postJson(`${ENDPOINT}/${entryId}/actions`, { values: { action } })
    if (!result.ok) {
      errorMessage.value = result.message
      return
    }
    await refresh()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '工班动作执行失败'
  }
}

async function postJson(path: string, body: Record<string, unknown>): Promise<{ ok: boolean; message: string }> {
  const response = await request(path, { method: 'POST', body: JSON.stringify(body) })
  if (!response.ok) {
    throw new Error(`接口返回 ${response.status}，操作未生效`)
  }
  const payload = await response.json()
  return { ok: Boolean(payload.ok), message: String(payload.message ?? '') }
}

async function reloadBoard() {
  try {
    const response = await request(`${ENDPOINT}/board`)
    if (response.ok) {
      const payload = await response.json()
      stats.value = payload.items ?? stats.value
    }
  } catch {
    // 看板取不到时保留上一次的数字，不清零误导现场。
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams()
  if (keyword.value) query.set('keyword', keyword.value)
  if (statusFilter.value) query.set('status', statusFilter.value)
  try {
    const response = await request(`${ENDPOINT}?${query.toString()}`)
    if (!response.ok) throw new Error('工班列表读取失败')
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '工班列表读取失败'
  }
}

async function reloadLedger() {
  try {
    const query = new URLSearchParams()
    if (ledgerFilter.value) query.set('review_status', ledgerFilter.value)
    const response = await request(`${ENDPOINT}/ledger?${query.toString()}`)
    if (!response.ok) throw new Error('台账读取失败')
    const payload = await response.json()
    ledgerRows.value = payload.items ?? []
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '工班台账读取失败'
  }
}

async function reviewLedger(item: Row) {
  const reviewer = (reviewers[Number(item.id)] ?? '').trim()
  if (!reviewer) {
    errorMessage.value = `请填写台账 ${item.id} 的复核人`
    return
  }
  errorMessage.value = ''
  try {
    const result = await postJson(`${ENDPOINT}/ledger/${item.id}/review`, { 复核人: reviewer })
    if (!result.ok) {
      errorMessage.value = result.message
      return
    }
    reviewers[Number(item.id)] = ''
    await reloadLedger()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '台账复核失败'
  }
}

function openHistory(row: Row) {
  historyEntry.value = row
}

async function refresh() {
  await Promise.all([reload(), reloadBoard(), reloadLedger()])
}

onMounted(refresh)
</script>

<style scoped>
.ledger-block {
  margin-top: 20px;
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px;
}
.ledger-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  margin-bottom: 10px;
}
.ledger-head h3 {
  margin: 0;
  font-size: 15px;
}
.filter-item.inline {
  display: flex;
  align-items: center;
  gap: 6px;
}
.filter-item.inline span {
  font-size: 12px;
  color: var(--muted);
}
.review-input {
  width: 90px;
  margin-right: 6px;
  padding: 2px 6px;
  border: 1px solid var(--border);
  border-radius: 4px;
}
.muted-text {
  color: var(--muted);
  font-size: 12px;
}
.modal-mask {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 20;
}
.modal-card {
  width: 460px;
  max-width: calc(100vw - 32px);
  max-height: 82vh;
  overflow: auto;
  background: #fff;
  border-radius: 10px;
  padding: 18px 20px;
}
.modal-title {
  margin: 0 0 6px;
  font-size: 16px;
}
.modal-tip {
  margin: 0 0 12px;
  color: var(--muted);
  font-size: 12px;
  line-height: 1.6;
}
.modal-field {
  margin-bottom: 10px;
}
.modal-field label span {
  display: block;
  font-size: 12px;
  color: var(--muted);
  margin-bottom: 4px;
}
.modal-field input {
  width: 100%;
  padding: 6px 8px;
  border: 1px solid var(--border);
  border-radius: 6px;
}
.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 14px;
}
</style>
