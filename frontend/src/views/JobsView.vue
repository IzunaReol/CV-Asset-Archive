<script setup lang="ts">
import { jobAction } from '../uiPolicy'
import { jobTypeLabels, jobStateLabels, jobNameText, jobSizeText, jobErrorText, jobTypeText, jobStateText, type useJobs } from '../composables/useJobs'
import type { MenuKey } from '../menuPermissions'

const props = defineProps<{ jobs: ReturnType<typeof useJobs>; canExport: boolean }>()
const emit = defineEmits<{ navigate: [page: MenuKey] }>()
const { rows: jobRows, total: jobTotal, page: jobPage, pageSize: jobPageSize,
  typeFilter: jobTypeFilter, stateFilter: jobStateFilter, createdFrom: jobCreatedFrom, createdTo: jobCreatedTo,
  pages: jobPages, load: loadJobs, download: downloadExport, retry: retryJob, cancel: cancelJob,
  resetFilters: resetJobFilters, applyFilters: applyJobFilters } = props.jobs
</script>

<template>
        <section class="page-head"><div><h1>任务中心</h1><p>查看导出和系统清理任务。</p></div></section>
        <section class="job-toolbar"><div class="job-count">当前页 <b>{{jobRows.length}}</b> 项 <span>· 全部 {{jobTotal}} 项</span></div><div class="job-filters"><select v-model="jobTypeFilter"><option value="">全部类型</option><option v-for="(label,key) in jobTypeLabels" :key="key" :value="key">{{label}}</option></select><select v-model="jobStateFilter"><option value="">全部状态</option><option v-for="(label,key) in jobStateLabels" :key="key" :value="key">{{label}}</option></select><label>开始时间<input v-model="jobCreatedFrom" type="datetime-local" step="1" /></label><label>结束时间<input v-model="jobCreatedTo" type="datetime-local" step="1" :min="jobCreatedFrom" /></label><button @click="resetJobFilters">重置</button><button @click="applyJobFilters">筛选</button></div></section>
        <section v-if="jobRows.length" class="data-table download-table"><div class="table-row head"><span>任务</span><span>任务创建时间</span><span>内容</span><span>大小</span><span>进度</span><span>类型</span><span>状态</span><span>操作</span></div><div v-for="job in jobRows" :key="job.id" class="table-row"><span class="job-name"><b :title="jobNameText(job)">{{jobNameText(job)}}</b><small v-if="job.error?.message" :title="jobErrorText(job.error.message)">{{jobErrorText(job.error.message)}}</small></span><span>{{job.created_at ? new Date(job.created_at).toLocaleString('zh-CN') : '时间未知'}}</span><span>{{job.input?.asset_count ?? job.input?.asset_ids?.length ?? 0}} 项</span><span>{{jobSizeText(job)}}</span><span class="progress"><i :style="{width:`${job.progress}%`}"></i><small>{{job.progress}}%</small></span><span>{{jobTypeText(job.type)}}</span><span :class="job.state==='failed'?'failed':job.state==='succeeded'?'done':job.state==='cancelled'?'cancelled':''">{{jobStateText(job.state)}}</span><button v-if="jobAction(job)==='download'" class="primary" @click="downloadExport(job.id)">下载</button><button v-else-if="canExport&&jobAction(job)==='retry'" @click="retryJob(job.id)">重试</button><button v-else-if="canExport&&jobAction(job)==='cancel'" class="danger-inline" @click="cancelJob(job)">取消</button></div></section>
        <div v-if="jobTotal" class="pagination"><span>第 {{jobPage}} / {{jobPages}} 页</span><label>每页 <select v-model="jobPageSize" @change="jobPage=1;loadJobs()"><option :value="20">20</option><option :value="50">50</option><option :value="100">100</option></select> 项</label><button :disabled="jobPage===1" @click="jobPage--;loadJobs()">‹</button><button :disabled="jobPage===jobPages" @click="jobPage++;loadJobs()">›</button></div>
        <section v-if="!jobTotal" class="empty"><b>暂无符合条件的任务</b><p>导出和系统清理任务会显示在这里。</p><button v-if="jobTypeFilter||jobStateFilter||jobCreatedFrom||jobCreatedTo" @click="resetJobFilters">清除筛选</button><button v-else @click="emit('navigate','library')">返回素材库</button></section>
</template>
