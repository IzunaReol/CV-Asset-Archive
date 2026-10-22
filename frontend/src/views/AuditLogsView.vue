<script setup lang="ts">
import { useAuditLogs } from '../composables/useAuditLogs'
import { auditActionLabels, auditObjectLabels, auditActionText, type createAuditPresentation } from '../auditPresentation'

const props = defineProps<{
  logs: ReturnType<typeof useAuditLogs>
  presentation: ReturnType<typeof createAuditPresentation>
}>()
const { rows: auditRows, loading: auditLoading, page: auditPage, pageSize: auditPageSize,
  total: auditTotal, query: auditQuery, action: auditAction, objectType: auditObjectType,
  createdFrom: auditCreatedFrom, createdTo: auditCreatedTo, detail: auditDetail, pages: auditPages,
  load: loadAuditLogs, exportCsv: exportAuditLogs, applyFilters: applyAuditFilters,
  resetFilters: resetAuditFilters, openDetail: openAuditDetail, closeDetail: closeAuditDetail } = props.logs
const { objectText: auditObjectText, changeEntries: auditChangeEntries, changesText: auditChangesText } = props.presentation
</script>

<template>
        <section class="page-head"><div><h1>系统日志</h1></div><button class="secondary" @click="exportAuditLogs">导出 CSV</button></section>
        <section class="content-panel audit-log-shell">
          <div class="audit-log-filters">
            <label class="audit-search-field"><span>关键字</span><input v-model="auditQuery" placeholder="搜索用户、对象、操作或请求 ID" @keyup.enter="applyAuditFilters" /></label>
            <label><span>操作类型</span><select v-model="auditAction"><option value="">全部操作</option><option v-for="(label,key) in auditActionLabels" :key="key" :value="key">{{label}}</option></select></label>
            <label><span>操作对象</span><select v-model="auditObjectType"><option value="">全部对象</option><option v-for="(label,key) in auditObjectLabels" :key="key" :value="key">{{label}}</option></select></label>
            <label><span>开始时间</span><input v-model="auditCreatedFrom" type="datetime-local" step="1" /></label>
            <label><span>结束时间</span><input v-model="auditCreatedTo" type="datetime-local" step="1" :min="auditCreatedFrom" /></label>
            <button class="secondary" @click="resetAuditFilters">重置</button><button class="primary" @click="applyAuditFilters">筛选</button>
          </div>
          <div class="toolbar"><div>当前页 <b>{{auditRows.length}}</b> 项 <span>· 全部 {{auditTotal}} 项</span></div></div>
          <div v-if="auditLoading" class="state-panel"><b>正在加载系统日志…</b></div>
          <div v-else-if="auditRows.length" class="data-table audit-log-table">
            <div class="table-row head"><span>时间</span><span>操作用户</span><span>操作</span><span>操作对象</span><span>变更内容</span><span>请求 ID</span></div>
            <div v-for="item in auditRows" :key="item.id" class="table-row"><span class="audit-time">{{new Date(item.created_at).toLocaleString('zh-CN')}}</span><b class="audit-actor">{{item.actor_username||item.actor_id||'系统'}}</b><span><i class="audit-action-badge">{{auditActionText(item.action)}}</i></span><span class="audit-object" :title="auditObjectText(item)">{{auditObjectText(item)}}</span><span class="audit-change-summary" :title="auditChangesText(item.changes)">{{auditChangesText(item.changes)}}</span><span class="audit-request"><code :title="item.request_id">{{item.request_id}}</code><button type="button" @click="openAuditDetail(item)">详情</button></span></div>
          </div>
          <section v-else class="empty"><b>暂无符合条件的系统日志</b><p>用户、素材、数据集和关联关系的重要操作会显示在这里。</p><button v-if="auditQuery||auditAction||auditObjectType||auditCreatedFrom||auditCreatedTo" @click="resetAuditFilters">清除筛选</button></section>
          <div v-if="auditTotal" class="pagination"><span>第 {{auditPage}} / {{auditPages}} 页</span><label>每页 <select v-model="auditPageSize" @change="auditPage=1;loadAuditLogs()"><option :value="20">20</option><option :value="50">50</option><option :value="100">100</option></select> 项</label><button :disabled="auditPage===1" @click="auditPage--;loadAuditLogs()">‹</button><button :disabled="auditPage===auditPages" @click="auditPage++;loadAuditLogs()">›</button></div>
        </section>

    <div v-if="auditDetail" class="detail-sheet-stage audit-detail-stage" @click.self="closeAuditDetail">
      <aside class="detail-sheet audit-detail-sheet">
        <button class="close" aria-label="关闭日志详情" @click="closeAuditDetail">×</button>
        <header><small>系统日志详情</small><h2>{{auditActionText(auditDetail.action)}}</h2><p>{{auditObjectText(auditDetail)}}</p></header>
        <section class="audit-detail-overview">
          <div><span>操作用户</span><b>{{auditDetail.actor_username||auditDetail.actor_id||'系统'}}</b></div>
          <div><span>操作时间</span><b>{{new Date(auditDetail.created_at).toLocaleString('zh-CN')}}</b></div>
          <div><span>操作类型</span><b>{{auditActionText(auditDetail.action)}}</b></div>
          <div><span>操作对象</span><b>{{auditObjectText(auditDetail)}}</b></div>
          <div><span>请求结果</span><b>{{auditDetail.outcome==='failed'?'失败':'成功'}}{{auditDetail.response_status?`（${auditDetail.response_status}）`:''}}</b></div>
          <div><span>客户端 IP</span><b>{{auditDetail.client_ip||'未记录'}}</b></div>
        </section>
        <section class="audit-detail-changes"><div class="audit-detail-title"><b>变更内容</b><span>{{auditChangeEntries(auditDetail.changes).length}} 项</span></div><div v-if="auditChangeEntries(auditDetail.changes).length" class="audit-change-list"><div v-for="entry in auditChangeEntries(auditDetail.changes)" :key="entry.key"><span>{{entry.label}}</span><p>{{entry.value}}</p></div></div><p v-else class="audit-no-changes">本次操作未记录字段变化。</p></section>
        <section class="audit-request-detail"><span>请求 ID</span><code>{{auditDetail.request_id}}</code></section>
      </aside>
    </div>
</template>
