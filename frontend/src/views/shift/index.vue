<template>
  <section class="page" data-module="shift">
    <header class="page-head">
      <div>
        <h2>工班管理</h2>
        <p class="page-desc">工班状态只能按 待交班 → 当班中 → 已交班 → 已休班 推进；看板人数随交班记录实时变化。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记工班</button>
        <button class="btn" type="button" @click="exportRows">导出工班清单</button>
      </div>
    </header>

    <!-- 看板：只统计当班中工班，交班后自动回落，不再沿用白班数据 -->
    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>工班编号</span>
        <input v-model="filters.keyword" placeholder="按工班编号检索" />
      </label>
      <label class="filter-item">
        <span>工班状态</span>
        <select v-model="filters.status">
          <option value="">全部</option>
          <option v-for="status in statuses" :key="status" :value="status">{{ status }}</option>
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
          <td v-for="column in columns" :key="column">{{ display(row, column) }}</td>
          <td class="row-actions">
            <button
              v-for="action in allowedActions(row)"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
            <button class="link" type="button" @click="showHistory(row)">变更记录</button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无工班数据，可先登记工班</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条工班记录</span>
      <span v-if="noticeMessage" class="notice-text">{{ noticeMessage }}</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <!-- 工班台账：交班记录自动落到待复核清单 -->
    <section class="ledger-block">
      <header class="page-head">
        <div>
          <h3>工班台账 · 交班复核</h3>
          <p class="page-desc">工班完成交班后自动生成一条记录，复核后从待复核清单划除。</p>
        </div>
        <div class="page-actions">
          <button
            v-for="tab in ledgerTabs"
            :key="tab.value"
            class="btn"
            :class="{ primary: ledgerFilter === tab.value }"
            type="button"
            @click="ledgerFilter = tab.value; loadLedger()"
          >
            {{ tab.label }}
          </button>
        </div>
      </header>
      <table class="data-table">
        <thead>
          <tr>
            <th>工班编号</th><th>工班名称</th><th>当班日期</th><th>作业时段</th>
            <th>当班组长</th><th>出勤人数</th><th>作业线数</th><th>交班时间</th><th>复核状态</th><th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="rec in ledgerRows" :key="String(rec.id)">
            <td>{{ rec['工班编号'] }}</td>
            <td>{{ rec['工班名称'] }}</td>
            <td>{{ rec['当班日期'] }}</td>
            <td>{{ rec['作业时段'] }}</td>
            <td>{{ rec['当班组长'] }}</td>
            <td>{{ rec['出勤人数'] }}</td>
            <td>{{ rec['作业线数'] }}</td>
            <td>{{ rec['交班时间'] }}</td>
            <td>{{ rec['复核状态'] }}</td>
            <td class="row-actions">
              <button v-if="!rec['已复核']" class="link" type="button" @click="reviewLedger(rec)">确认复核</button>
              <span v-else class="empty-state">已归档</span>
            </td>
          </tr>
          <tr v-if="!ledgerRows.length">
            <td colspan="10" class="empty-state">
              {{ ledgerFilter === 'pending' ? '待复核清单为空' : '台账暂无记录' }}
            </td>
          </tr>
        </tbody>
      </table>
    </section>

    <!-- 登记工班弹窗 -->
    <div v-if="modal === 'create'" class="modal-mask" @click.self="modal = ''">
      <form class="modal" @submit.prevent="submitCreate">
        <h3>登记工班</h3>
        <p class="page-desc">登记后状态为「待交班」，开始当班时校验同工班同一天不得重复当班。</p>
        <label v-for="field in createFields" :key="field.name" class="form-item">
          <span>{{ field.label }}{{ field.required ? ' *' : '' }}</span>
          <input v-model="createForm[field.name]" :placeholder="field.placeholder ?? ''" />
        </label>
        <div class="modal-actions">
          <button class="btn" type="button" @click="modal = ''">取消</button>
          <button class="btn primary" type="submit">登记</button>
        </div>
      </form>
    </div>

    <!-- 临时调配弹窗：先登记作业时段与组长 -->
    <div v-if="modal === 'dispatch'" class="modal-mask" @click.self="modal = ''">
      <form class="modal" @submit.prevent="submitDispatch">
        <h3>临时调配登记</h3>
        <p class="page-desc">调配不改变工班状态，登记后回到「当班中」。作业时段与组长为必填。</p>
        <label class="form-item">
          <span>作业时段 *</span>
          <input v-model="dispatchForm.作业时段" placeholder="如 2026-09-30 14:00-16:00" />
        </label>
        <label class="form-item">
          <span>组长 *</span>
          <input v-model="dispatchForm.组长" placeholder="本次调配负责组长" />
        </label>
        <label class="form-item">
          <span>备注</span>
          <input v-model="dispatchForm.备注" placeholder="调配事由（选填）" />
        </label>
        <div class="modal-actions">
          <button class="btn" type="button" @click="modal = ''">取消</button>
          <button class="btn primary" type="submit">登记调配</button>
        </div>
      </form>
    </div>

    <!-- 变更记录弹窗 -->
    <div v-if="modal === 'history'" class="modal-mask" @click.self="modal = ''">
      <div class="modal">
        <h3>变更记录 · {{ historyTarget?.['工班编号'] }}</h3>
        <table class="data-table">
          <thead>
            <tr><th>时间</th><th>动作</th><th>作业时段</th><th>组长</th><th>变更后状态</th></tr>
          </thead>
          <tbody>
            <tr v-for="(item, index) in historyRows" :key="index">
              <td>{{ item['时间'] }}</td>
              <td>{{ item['动作'] }}</td>
              <td>{{ item['作业时段'] }}</td>
              <td>{{ item['组长'] }}</td>
              <td>{{ item['变更后状态'] }}</td>
            </tr>
            <tr v-if="!historyRows.length">
              <td colspan="5" class="empty-state">暂无变更记录</td>
            </tr>
          </tbody>
        </table>
        <div class="modal-actions">
          <button class="btn primary" type="button" @click="modal = ''">关闭</button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>
type LedgerRow = Record<string, string | number | boolean | null>
type HistoryItem = Record<string, string>

const ENDPOINT = '/api/shift'
const columns = ['工班编号', '工班名称', '当班组长', '作业线数', '出勤人数', '作业时段', '作业效率', '工班状态']
const statuses = ['待交班', '当班中', '已交班', '已休班']
// 每个状态下允许推进的动作：顺序推进、不可跳级、已休班无动作
const ACTIONS_BY_STATUS: Record<string, string[]> = {
  待交班: ['开始当班'],
  当班中: ['更新资料', '临时调配', '完成交班'],
  已交班: ['下班休班'],
  已休班: [],
}
const ledgerTabs = [
  { label: '待复核', value: 'pending' },
  { label: '已复核', value: 'reviewed' },
  { label: '全部', value: 'all' },
] as const
const createFields: { name: string; label: string; required: boolean; placeholder?: string }[] = [
  { name: '工班编号', label: '工班编号', required: true },
  { name: '工班名称', label: '工班名称', required: true },
  { name: '当班组长', label: '当班组长', required: true },
  { name: '作业时段', label: '作业时段', required: false, placeholder: '如 2026-09-30 夜班' },
  { name: '出勤人数', label: '出勤人数', required: false, placeholder: '当班中可补录，交班时必填' },
  { name: '作业线数', label: '作业线数', required: false, placeholder: '当班中可补录，交班时必填' },
]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const noticeMessage = ref('')
const filters = reactive<{ keyword: string; status: string }>({ keyword: '', status: '' })
const stats = ref([
  { label: '当班工班数', value: 0 },
  { label: '出勤总人数', value: 0 },
  { label: '完成作业线', value: 0 },
])

const ledgerRows = ref<LedgerRow[]>([])
const ledgerFilter = ref<string>('pending')

const modal = ref<'' | 'create' | 'dispatch' | 'history'>('')
const createForm = reactive<Record<string, string>>({})
const dispatchForm = reactive<Record<string, string>>({ 作业时段: '', 组长: '', 备注: '' })
const dispatchTarget = ref<Row | null>(null)
const historyRows = ref<HistoryItem[]>([])
const historyTarget = ref<Row | null>(null)

function allowedActions(row: Row): string[] {
  return ACTIONS_BY_STATUS[String(row.status ?? '')] ?? []
}

function display(row: Row, column: string): string | number | null {
  const value = row[column]
  return value === '' || value === null || value === undefined ? '—' : value
}

function resetFilters() {
  filters.keyword = ''
  filters.status = ''
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export/all`, '_blank')
}

async function postAction(path: string, body: Record<string, unknown>) {
  const response = await request(path, { method: 'POST', body: JSON.stringify(body) })
  const payload = await response.json().catch(() => null)
  if (!response.ok || !payload?.ok) {
    throw new Error(payload?.message || '操作未生效，请稍后重试')
  }
  errorMessage.value = ''
  await Promise.all([reload(), loadBoard(), loadLedger()])
  return payload.message as string
}

function openCreate() {
  for (const field of createFields) createForm[field.name] = ''
  modal.value = 'create'
}

async function submitCreate() {
  try {
    const message = await postAction(ENDPOINT, { values: { ...createForm } })
    modal.value = ''
    noticeMessage.value = message
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '工班登记失败'
  }
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    if (action === '更新资料') {
      await promptUpdate(row)
      return
    }
    if (action === '临时调配') {
      dispatchTarget.value = row
      dispatchForm.作业时段 = String(row['作业时段'] ?? '')
      dispatchForm.组长 = String(row['当班组长'] ?? '')
      dispatchForm.备注 = ''
      modal.value = 'dispatch'
      return
    }
    const confirmText = action === '完成交班'
      ? '确认完成交班？出勤人数与作业线数需已登记，交班后将进入台账待复核清单。'
      : `确认执行「${action}」？`
    if (!window.confirm(confirmText)) return
    const message = await postAction(
      `${ENDPOINT}/${row.id}/actions`,
      { values: { action } },
    )
    noticeMessage.value = message
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '工班操作失败'
  }
}

async function promptUpdate(row: Row) {
  const attendance = window.prompt('出勤人数（正整数，交班必填）', String(row['出勤人数'] ?? ''))
  if (attendance === null) return
  const lines = window.prompt('作业线数（正整数，交班必填）', String(row['作业线数'] ?? ''))
  if (lines === null) return
  try {
    const response = await request(`${ENDPOINT}/${row.id}`, {
      method: 'PATCH',
      body: JSON.stringify({ values: { 出勤人数: attendance.trim(), 作业线数: lines.trim() } }),
    })
    const payload = await response.json().catch(() => null)
    if (!response.ok || !payload?.ok) {
      throw new Error(payload?.message || '资料更新失败')
    }
    await Promise.all([reload(), loadBoard()])
    noticeMessage.value = payload.message
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '资料更新失败'
  }
}

async function submitDispatch() {
  if (!dispatchTarget.value) return
  try {
    const message = await postAction(
      `${ENDPOINT}/${dispatchTarget.value.id}/actions`,
      { values: { action: '临时调配', ...dispatchForm } },
    )
    modal.value = ''
    noticeMessage.value = message
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '临时调配登记失败'
  }
}

async function showHistory(row: Row) {
  historyTarget.value = row
  historyRows.value = []
  modal.value = 'history'
  try {
    const response = await request(`${ENDPOINT}/${row.id}/history`)
    if (!response.ok) throw new Error('变更记录读取失败')
    historyRows.value = await response.json()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '变更记录读取失败'
  }
}

async function reviewLedger(rec: LedgerRow) {
  if (!window.confirm('确认该交班记录复核通过？')) return
  try {
    const response = await request(`${ENDPOINT}/ledger/${rec.id}/review`, { method: 'POST', body: '{}' })
    const payload = await response.json().catch(() => null)
    if (!response.ok || !payload?.ok) {
      throw new Error(payload?.message || '复核失败')
    }
    await loadLedger()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '台账复核失败'
  }
}

async function loadBoard() {
  try {
    const response = await request(`${ENDPOINT}/board`)
    if (!response.ok) return
    const payload = await response.json()
    stats.value = [
      { label: '当班工班数', value: Number(payload['当班工班数'] ?? 0) },
      { label: '出勤总人数', value: Number(payload['出勤总人数'] ?? 0) },
      { label: '完成作业线', value: Number(payload['完成作业线'] ?? 0) },
    ]
  } catch {
    // 看板取不到时保持 0，不阻断列表
  }
}

async function loadLedger() {
  try {
    const params = new URLSearchParams()
    if (ledgerFilter.value === 'pending') params.set('reviewed', 'false')
    if (ledgerFilter.value === 'reviewed') params.set('reviewed', 'true')
    const response = await request(`${ENDPOINT}/ledger?${params.toString()}`)
    if (!response.ok) throw new Error('台账读取失败')
    ledgerRows.value = await response.json()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '工班台账读取失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams()
  if (filters.keyword.trim()) query.set('keyword', filters.keyword.trim())
  if (filters.status) query.set('status', filters.status)
  try {
    const response = await request(`${ENDPOINT}?${query.toString()}`)
    if (!response.ok) {
      throw new Error('工班列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '工班列表读取失败'
  }
}

onMounted(() => {
  void reload()
  void loadBoard()
  void loadLedger()
})
</script>

<style scoped>
.page-actions {
  display: flex;
  gap: 8px;
}
.ledger-block {
  margin-top: 24px;
}
.ledger-block h3 {
  margin: 0;
  font-size: 16px;
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
.modal {
  width: 420px;
  max-height: 80vh;
  overflow: auto;
  background: #fff;
  border-radius: 10px;
  padding: 18px 20px;
}
.modal h3 {
  margin: 0 0 6px;
}
.form-item {
  display: block;
  margin: 10px 0;
  font-size: 13px;
}
.form-item span {
  display: block;
  color: var(--muted);
  margin-bottom: 4px;
}
.form-item input {
  width: 100%;
  box-sizing: border-box;
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
.notice-text {
  color: #067647;
}
</style>
