<script setup lang="ts">
defineProps<{
  title: string
  message: string
  actionText: string
  busy: boolean
  usageImpact: any | null
  deleteStage: number
}>()
defineEmits<{ cancel: []; confirm: [] }>()
</script>

<template>
  <div class="modal-stage confirm-stage">
    <section class="upload-dialog compact-dialog confirm-dialog" :class="{'usage-confirm-dialog':usageImpact}">
      <h2>{{title}}</h2><p>{{message}}</p>
      <div v-if="usageImpact" class="usage-impact" aria-label="素材使用影响">
        <b>使用影响：存在 {{usageImpact.affected_count}} 项关联关系</b>
        <small v-if="usageImpact.details_truncated">仅展示前 {{usageImpact.items.length}} 项有关联的素材。</small>
        <small v-if="deleteStage">删除后会移除关联数据集和关联版本中的素材记录，历史版本内容将变化；从回收站还原素材不会恢复这些关联。</small>
        <div class="usage-impact-list">
          <article v-for="item in usageImpact.items" :key="item.id">
            <strong>{{item.name}}</strong>
            <span v-if="item.current_datasets.length">关联数据集：{{item.current_datasets.map((row:any)=>row.name).join('、')}}</span>
            <span v-if="item.historical_versions.length">关联版本：{{item.historical_versions.map((row:any)=>`${row.dataset_name} ${row.version}`).join('、')}}</span>
            <span v-if="item.models.length">关联模型：{{item.models.map((row:any)=>row.name).join('、')}}</span>
            <span v-if="item.other_relation_count">其他关联关系：{{item.other_relation_count}} 条</span>
          </article>
        </div>
      </div>
      <div class="dialog-actions"><button class="secondary" :disabled="busy" @click="$emit('cancel')">取消</button><button :class="message.includes('覆盖原文件')?'confirm-primary':'confirm-delete'" :disabled="busy" @click="$emit('confirm')">{{busy?'正在处理…':actionText}}</button></div>
    </section>
  </div>
</template>
