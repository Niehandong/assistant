import { CopyOutlined } from '@ant-design/icons';
import { App, Button } from 'antd';
import { copyText } from '@/utils/clipboard';

/** 代码块 + 复制按钮 */
export default function CodeBlock({ code, label }: { code: string; label: string }) {
  const { message } = App.useApp();
  const copy = async () => {
    if (await copyText(code)) void message.success('已复制');
    else void message.error('复制失败，请手动选中复制');
  };
  return (
    <div style={{ position: 'relative', marginBottom: 16 }}>
      <Button
        size="small"
        icon={<CopyOutlined />}
        aria-label={`复制${label}`}
        onClick={() => void copy()}
        style={{ position: 'absolute', top: 8, right: 8 }}
      >
        复制
      </Button>
      <pre
        style={{
          margin: 0,
          padding: '12px 16px',
          paddingRight: 80,
          background: '#f6f8fa',
          borderRadius: 6,
          overflow: 'auto',
          fontSize: 13,
          lineHeight: 1.6,
        }}
      >
        <code>{code}</code>
      </pre>
    </div>
  );
}
