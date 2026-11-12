import { PageContainer } from '@ant-design/pro-components';
import { Alert, Card, Table, Tag, Typography } from 'antd';
import CodeBlock from './CodeBlock';
import {
  ERROR_EXAMPLES,
  ERROR_ROWS,
  REQUEST_NOTES,
  REQUEST_PARAMS,
  SUCCESS_EXAMPLE,
  SUCCESS_NOTE,
  buildCurl,
  buildCurlFull,
  buildEndpoint,
  buildPython,
} from './content';

const { Title, Paragraph, Text } = Typography;

/** API 文档（F-18）：静态内容，示例与契约 tech-design-m3.md 5.4 一致 */
export default function ApiDocsPage() {
  const endpoint = buildEndpoint(window.location.origin);
  const example = buildEndpoint(window.location.origin, 10);

  return (
    <PageContainer title="开放检索 API 文档">
      <Card>
        <Title level={4}>1. 调用地址</Title>
        <CodeBlock label="调用地址" code={`POST ${endpoint}`} />
        <Paragraph>
          <Text code>{'{dataset_id}'}</Text> 为知识库
          ID：在「知识库」中进入目标知识库详情页，左侧信息区显示
          <Text strong>“知识库 ID”</Text>。一次调用只检索一个知识库。
        </Paragraph>

        <Title level={4}>2. 鉴权方式</Title>
        <Paragraph>
          在「开放平台 &gt; 我的 API
          密钥」创建密钥（明文只显示一次，请妥善保存），调用时通过请求头传递，无需登录：
        </Paragraph>
        <CodeBlock label="鉴权请求头" code={'Authorization: Bearer kb-AbCd...'} />
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message="密钥可检索的知识库 = 创建人当前有权访问的知识库（与密钥设置的指定范围取交集），权限变化即时生效。"
        />

        <Title level={4}>3. 请求参数</Title>
        <Paragraph>请求体为 JSON（Content-Type: application/json）：</Paragraph>
        <Table
          size="small"
          bordered
          pagination={false}
          rowKey="name"
          dataSource={REQUEST_PARAMS}
          style={{ marginBottom: 12 }}
          columns={[
            {
              title: '字段',
              dataIndex: 'name',
              width: 160,
              render: (v: string) => <Text code>{v}</Text>,
            },
            { title: '类型', dataIndex: 'type', width: 80 },
            {
              title: '必填',
              dataIndex: 'required',
              width: 70,
              render: (v: boolean) => (v ? <Tag color="error">是</Tag> : '否'),
            },
            { title: '说明与取值', dataIndex: 'rule' },
          ]}
        />
        <ul>
          {REQUEST_NOTES.map((n) => (
            <li key={n}>{n}</li>
          ))}
        </ul>

        <Title level={4}>4. 请求示例</Title>
        <Paragraph>curl：</Paragraph>
        <CodeBlock label="curl 示例" code={buildCurl(example)} />
        <Paragraph>指定全部可选参数：</Paragraph>
        <CodeBlock label="完整参数 curl 示例" code={buildCurlFull(example)} />
        <Paragraph>Python（requests）：</Paragraph>
        <CodeBlock label="Python 示例" code={buildPython(example)} />

        <Title level={4}>5. 成功响应（HTTP 200）</Title>
        <CodeBlock label="成功响应示例" code={SUCCESS_EXAMPLE} />
        <Paragraph type="secondary">{SUCCESS_NOTE}</Paragraph>

        <Title level={4}>6. 失败响应与错误码</Title>
        <Paragraph>
          失败时 HTTP 状态码 = code 的整数商（code ÷ 1000），响应体仍为统一格式；
          <Text code>data.error_type</Text> 用于程序判断，<Text code>data.request_id</Text>{' '}
          便于排查。
        </Paragraph>
        <CodeBlock label="失败响应示例" code={ERROR_EXAMPLES} />
        <Table
          size="small"
          bordered
          pagination={false}
          rowKey="code"
          dataSource={ERROR_ROWS}
          columns={[
            { title: 'HTTP 状态', dataIndex: 'http', width: 100 },
            { title: 'code', dataIndex: 'code', width: 100 },
            {
              title: 'error_type',
              dataIndex: 'errorType',
              width: 210,
              render: (v: string) => <Text code>{v}</Text>,
            },
            { title: '说明', dataIndex: 'message', width: 220 },
            { title: '备注', dataIndex: 'note', render: (v?: string) => v ?? '-' },
          ]}
        />
      </Card>
    </PageContainer>
  );
}
