import { useQuery } from '@tanstack/react-query';
import { Alert, App, Input, Modal, Typography } from 'antd';
import { useState } from 'react';
import { datasetApi } from '@/services/kb';
import type { DatasetItem } from '@/services/types/kb-contract';
import { notifyError } from '@/utils/notify';

interface Props {
  dataset: DatasetItem;
  onClose: () => void;
  onDeleted: () => void;
}

/** 删除确认：需输入知识库名称一致才可提交；提示将失去访问权限的分配对象数（取详情的 assignment_count） */
export default function DeleteDatasetModal({ dataset, onClose, onDeleted }: Props) {
  const { message } = App.useApp();
  const [input, setInput] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const { data: detail, isError } = useQuery({
    queryKey: ['kb-dataset-detail', dataset.id],
    queryFn: () => datasetApi.detail(dataset.id),
  });

  const submit = async () => {
    setSubmitting(true);
    try {
      await datasetApi.remove(dataset.id, { confirm_name: input });
      void message.success('知识库已删除');
      onDeleted();
    } catch (err) {
      notifyError(err);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal
      open
      title={`删除知识库「${dataset.name}」`}
      okText="删除"
      okButtonProps={{ danger: true, disabled: input !== dataset.name, loading: submitting }}
      cancelButtonProps={{ disabled: submitting }}
      maskClosable={false}
      onOk={submit}
      onCancel={onClose}
      destroyOnClose
    >
      <Alert
        type="warning"
        showIcon
        style={{ marginBottom: 16 }}
        message="删除后知识库及其文档、分段将一并删除，正在处理的文档任务将被取消，且不可恢复。"
        description={
          detail
            ? `共有 ${detail.assignment_count} 个分配对象将失去访问权限`
            : isError
              ? '分配对象数量暂无法获取，所有被分配的对象都将失去访问权限'
              : '正在获取分配对象数量…'
        }
      />
      <Typography.Paragraph>
        请输入知识库名称 <Typography.Text strong>{dataset.name}</Typography.Text> 以确认删除：
      </Typography.Paragraph>
      <Input
        value={input}
        onChange={(e) => setInput(e.target.value)}
        placeholder="输入知识库名称"
        status={input && input !== dataset.name ? 'error' : undefined}
        onPressEnter={() => input === dataset.name && void submit()}
      />
    </Modal>
  );
}
