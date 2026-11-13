import { useQueryClient } from '@tanstack/react-query';
import { App } from 'antd';
import { useState } from 'react';
import { segmentApi } from '@/services/kb';
import type { ChildChunkItem, SegmentItem } from '@/services/types/kb-contract';
import { notifyError } from '@/utils/notify';
import { datasetDetailKey } from '../useDataset';
import { buildUpdateBody, classifySaveError, type SaveErrorKind } from './logic';

export type SaveResult = { ok: true } | { ok: false; kind: SaveErrorKind; message: string };

/** 分段/子块写操作：成功后统一刷新分段列表、文档列表与知识库统计 */
export function useSegmentActions(datasetId: number, documentId: number) {
  const { message, modal } = App.useApp();
  const qc = useQueryClient();
  const [busy, setBusy] = useState<string[]>([]);

  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ['kb-segments', 'normal', datasetId, documentId] });
    void qc.invalidateQueries({ queryKey: ['kb-documents', datasetId] });
    void qc.invalidateQueries({ queryKey: ['kb-document', datasetId, documentId] });
    void qc.invalidateQueries({ queryKey: datasetDetailKey(datasetId) });
  };

  /** 保存类操作：409511 提示并刷新，其余错误交调用方在表单内展示 */
  const guarded = async (fn: () => Promise<unknown>, okText: string): Promise<SaveResult> => {
    try {
      await fn();
      void message.success(okText);
      refresh();
      return { ok: true };
    } catch (err) {
      const r = classifySaveError(err);
      if (r.kind === 'conflict') {
        void message.warning(r.message);
        refresh();
      }
      return { ok: false, ...r };
    }
  };

  const withBusy = async (id: string, fn: () => Promise<void>) => {
    setBusy((b) => [...b, id]);
    try {
      await fn();
    } finally {
      setBusy((b) => b.filter((x) => x !== id));
    }
  };

  const toggleEnabled = (seg: SegmentItem, enabled: boolean) =>
    withBusy(`s${seg.id}`, async () => {
      try {
        await segmentApi.setEnabled(datasetId, seg.id, enabled);
        void message.success(enabled ? '已启用' : '已禁用');
      } catch (err) {
        notifyError(err);
      }
      refresh();
    });

  const removeSegment = (seg: SegmentItem) =>
    modal.confirm({
      title: `确认删除分段 #${seg.position}？`,
      content:
        seg.segment_type === 'parent'
          ? '父块及其全部子块将一并删除，删除后不可恢复。'
          : '删除后不可恢复。',
      okText: '删除',
      okButtonProps: { danger: true },
      onOk: () =>
        withBusy(`s${seg.id}`, async () => {
          try {
            await segmentApi.remove(datasetId, seg.id);
            void message.success('已删除');
          } catch (err) {
            notifyError(err);
          }
          refresh();
        }),
    });

  const saveSegment = (seg: SegmentItem, form: { content: string; keywords: string[] }) =>
    guarded(
      () => segmentApi.update(datasetId, seg.id, buildUpdateBody(seg, form)),
      seg.segment_type === 'parent' ? '已保存，子块将重新生成' : '已保存，索引更新中',
    );

  const createSegment = (form: { content: string; keywords: string[] }) =>
    guarded(
      () =>
        segmentApi.create(datasetId, documentId, {
          content: form.content.trim(),
          keywords: form.keywords,
        }),
      '已新增分段，索引完成后参与检索',
    );

  const createChild = (segmentId: number, content: string) =>
    guarded(
      () => segmentApi.createChild(datasetId, segmentId, { content: content.trim() }),
      '已新增子块',
    );

  const saveChild = (child: ChildChunkItem, content: string) =>
    guarded(
      () =>
        segmentApi.updateChild(datasetId, child.id, {
          content: content.trim(),
          version: child.version,
        }),
      '已保存，索引更新中',
    );

  const removeChild = (child: ChildChunkItem) =>
    modal.confirm({
      title: `确认删除子块 #${child.position}？`,
      content: '删除后不可恢复。',
      okText: '删除',
      okButtonProps: { danger: true },
      onOk: () =>
        withBusy(`c${child.id}`, async () => {
          try {
            await segmentApi.removeChild(datasetId, child.id);
            void message.success('已删除');
          } catch (err) {
            notifyError(err);
          }
          refresh();
        }),
    });

  return {
    busy,
    refresh,
    toggleEnabled,
    removeSegment,
    saveSegment,
    createSegment,
    createChild,
    saveChild,
    removeChild,
  };
}
