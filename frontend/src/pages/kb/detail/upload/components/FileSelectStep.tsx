import { CloseCircleFilled, InboxOutlined } from '@ant-design/icons';
import { App, Button, List, Progress, Space, Tag, Typography, Upload } from 'antd';
import { useRef } from 'react';
import { formatFileSize } from '@/utils/format';
import { MAX_FILES, type UploadItem } from '../fileCheck';

interface Props {
  items: UploadItem[];
  onAdd: (files: File[]) => void;
  onRemove: (uid: string) => void;
  onRetry: (uid: string) => void;
  onNext: () => void;
  nextDisabled: boolean;
}

export default function FileSelectStep({
  items,
  onAdd,
  onRemove,
  onRetry,
  onNext,
  nextDisabled,
}: Props) {
  const { message } = App.useApp();
  const buffer = useRef<File[]>([]);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // antd 对每个文件单独回调 beforeUpload：合并为一批再交给页面，便于统一做 20 个上限判断
  const collect = (file: File) => {
    buffer.current.push(file);
    if (!timer.current) {
      timer.current = setTimeout(() => {
        const batch = buffer.current;
        buffer.current = [];
        timer.current = null;
        onAdd(batch);
      }, 0);
    }
    return false;
  };

  const invalidCount = items.filter((i) => i.status === 'invalid' || i.status === 'error').length;

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Upload.Dragger
        multiple
        showUploadList={false}
        beforeUpload={collect}
        disabled={items.length >= MAX_FILES}
      >
        <p className="ant-upload-drag-icon">
          <InboxOutlined />
        </p>
        <p className="ant-upload-text">点击或拖拽文件到此处上传</p>
        <p className="ant-upload-hint">
          支持 TXT、Markdown、PDF（文本型）、DOCX、XLSX/XLS、CSV、HTML、PPTX；单个文件不超过 15
          MB，一次最多 {MAX_FILES} 个文件
        </p>
      </Upload.Dragger>
      {items.length > 0 && (
        <List
          size="small"
          bordered
          header={
            <Space>
              <span>
                已选择 {items.length} / {MAX_FILES} 个文件
              </span>
              {invalidCount > 0 && <Tag color="error">{invalidCount} 个文件有问题</Tag>}
            </Space>
          }
          dataSource={items}
          renderItem={(it) => (
            <List.Item
              key={it.uid}
              actions={[
                it.status === 'error' && (
                  <Button key="retry" type="link" size="small" onClick={() => onRetry(it.uid)}>
                    重试
                  </Button>
                ),
                <Button key="rm" type="link" size="small" danger onClick={() => onRemove(it.uid)}>
                  移除
                </Button>,
              ].filter(Boolean)}
            >
              <Space direction="vertical" size={0} style={{ width: '100%' }}>
                <Space>
                  <Typography.Text
                    type={it.status === 'invalid' || it.status === 'error' ? 'danger' : undefined}
                  >
                    {(it.status === 'invalid' || it.status === 'error') && <CloseCircleFilled />}{' '}
                    {it.file.name}
                  </Typography.Text>
                  <Typography.Text type="secondary">{formatFileSize(it.file.size)}</Typography.Text>
                  {it.status === 'done' && <Tag color="success">已上传</Tag>}
                </Space>
                {(it.status === 'invalid' || it.status === 'error') && (
                  <Typography.Text type="danger" style={{ fontSize: 12 }}>
                    {it.error}
                  </Typography.Text>
                )}
                {(it.status === 'uploading' || it.status === 'queued') && (
                  <Progress
                    percent={it.progress}
                    size="small"
                    status="active"
                    format={(p) => (it.status === 'queued' ? '等待中' : `${p}%`)}
                  />
                )}
              </Space>
            </List.Item>
          )}
        />
      )}
      <Button
        type="primary"
        disabled={nextDisabled}
        onClick={() => {
          if (nextDisabled) {
            void message.warning('请先上传至少一个有效文件');
            return;
          }
          onNext();
        }}
      >
        下一步
      </Button>
    </Space>
  );
}
