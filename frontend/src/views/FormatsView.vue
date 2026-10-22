<script setup lang="ts">
defineProps<{ rows: any[]; canManage: boolean; loaded: boolean; availableTypes: string[]; typeLabels: Record<string, string> }>()
defineEmits<{ create: []; edit: [row: any]; remove: [row: any] }>()
</script>

<template>
  <section class="page-head"><div><h1>格式管理</h1></div><button v-if="canManage && loaded && availableTypes.length" class="primary" @click="$emit('create')">＋ 新增格式</button></section>
  <section class="tag-admin"><article v-for="row in rows" :key="row.asset_type"><div><b>{{typeLabels[row.asset_type] || row.asset_type}}</b><code>{{row.remark || '暂无备注'}}</code></div><p>{{(row.extensions || []).join(' / ') || '暂无文件格式'}}</p><div v-if="canManage" class="tag-actions"><button @click="$emit('edit',row)">修改</button><button v-if="!row.built_in" @click="$emit('remove',row)">删除</button></div></article></section>
</template>
