<script setup lang="ts">
import { canDeleteTag } from '../uiPolicy'

defineProps<{ rows: any[]; canManage: boolean }>()
defineEmits<{ create: []; edit: [tag: any]; remove: [key: string, name: string] }>()
</script>

<template>
  <section class="page-head"><div><h1>标签管理</h1></div><button v-if="canManage" class="primary" @click="$emit('create')">＋ 新建标签字段</button></section>
  <section class="tag-admin"><article v-for="tag in rows" :key="tag.key"><div><span class="tag-dot" :style="{background:tag.color}"></span><b>{{tag.name}}</b><code>{{tag.key}}</code></div><p>{{(tag.values || []).join(' / ') || '允许自由输入'}}</p><div v-if="canManage" class="tag-actions"><button @click="$emit('edit',tag)">修改</button><button v-if="canDeleteTag(tag)" @click="$emit('remove',tag.key,tag.name)">删除</button></div></article></section>
</template>
