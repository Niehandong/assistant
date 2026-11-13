import { ArrowLeftOutlined } from '@ant-design/icons';
import { PageContainer } from '@ant-design/pro-components';
import {
  Alert,
  Button,
  Card,
  Descriptions,
  Flex,
  Menu,
  Result,
  Skeleton,
  Space,
  Tag,
  Typography,
} from 'antd';
import { Link, Outlet, useLocation, useNavigate, useParams } from 'react-router-dom';
import { usePermission } from '@/access/usePermission';
import DatasetIcon from '@/components/DatasetIcon';
import { spineColor } from '@/components/spineColor';
import { isApiError } from '@/utils/error';
import { formatNumber } from '@/utils/format';
import {
  CHUNK_MODE_UNSET_TEXT,
  PERMISSION_LABEL,
  SEARCH_METHOD_LABEL,
  buildStats,
  modelDisabledHint,
  ownerText,
} from '../list/logic';
import { activeNavKey, buildNavItems } from './navItems';
import { useDatasetQuery } from './useDataset';

/** 知识库详情布局：左侧信息与导航，右侧子页面（Outlet） */
export default function DatasetLayout() {
  const { id: idParam } = useParams();
  const id = Number(idParam);
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const can = usePermission();
  const { data, isLoading, error, refetch } = useDatasetQuery(id);

  const back = (
    <Link to="/kb/datasets">
      <ArrowLeftOutlined /> 返回我的知识库
    </Link>
  );

  if (isLoading) {
    return (
      <PageContainer title={false}>
        <Skeleton active paragraph={{ rows: 8 }} />
      </PageContainer>
    );
  }
  if (error || !data) {
    const notFound = isApiError(error) && (error.code === 404000 || error.status === 404);
    return (
      <PageContainer title={false}>
        <Result
          status={notFound ? '404' : 'error'}
          title={notFound ? '知识库不存在或您无权访问' : '加载失败'}
          subTitle={notFound ? undefined : (error as Error | null)?.message}
          extra={
            notFound ? (
              <Button type="primary" onClick={() => navigate('/kb/datasets')}>
                返回我的知识库
              </Button>
            ) : (
              <Space>
                <Button type="primary" onClick={() => void refetch()}>
                  重试
                </Button>
                {back}
              </Space>
            )
          }
        />
      </PageContainer>
    );
  }

  const stats = buildStats(data);
  const hint = modelDisabledHint(data);
  const items = buildNavItems(data.my_permission, can);
  const active = activeNavKey(pathname, id);
  const spine = spineColor(data.icon);

  return (
    <PageContainer title={false} breadcrumbRender={false}>
      <Flex gap={16} align="flex-start">
        <Card
          style={{ width: 280, flex: 'none', overflow: 'hidden' }}
          size="small"
          styles={{ body: { paddingTop: 16 } }}
        >
          <div
            aria-hidden
            style={{
              height: 6,
              background: spine,
              margin: '-8px -12px 0',
              position: 'relative',
              top: -8,
            }}
          />
          <Space direction="vertical" size={12} style={{ width: '100%' }}>
            {back}
            <Flex gap={8} align="center">
              <DatasetIcon name={data.icon} style={{ fontSize: 28, color: spine }} />
              <strong className="kb-serif" style={{ wordBreak: 'break-all', fontSize: 16 }}>
                {data.name}
              </strong>
            </Flex>
            {data.description && <span style={{ color: '#666' }}>{data.description}</span>}
            <Space size={[4, 4]} wrap>
              <Tag>{PERMISSION_LABEL[data.my_permission]}</Tag>
              <Tag>{stats.chunkModeUnset ? CHUNK_MODE_UNSET_TEXT : stats.chunkModeText}</Tag>
              <Tag>{SEARCH_METHOD_LABEL[data.search_method]}</Tag>
            </Space>
            <Descriptions column={1} size="small" colon={false}>
              <Descriptions.Item label="知识库 ID">
                <Typography.Text copyable={{ tooltips: ['复制', '已复制'] }}>
                  {data.id}
                </Typography.Text>
              </Descriptions.Item>
              <Descriptions.Item label="文档">{stats.docText}</Descriptions.Item>
              <Descriptions.Item label={stats.segmentLabel}>{stats.segmentText}</Descriptions.Item>
              <Descriptions.Item label="字符">{formatNumber(data.char_count)}</Descriptions.Item>
              <Descriptions.Item label="所有者">{ownerText(data)}</Descriptions.Item>
              <Descriptions.Item label="向量模型">{data.embedding_model.name}</Descriptions.Item>
            </Descriptions>
            <Menu
              mode="inline"
              selectedKeys={[active]}
              items={items.map((i) => ({ key: i.key, label: i.label }))}
              onClick={({ key }) => {
                const target = items.find((i) => i.key === key);
                if (target) navigate(`/kb/datasets/${id}/${target.path}`);
              }}
              style={{ borderInlineEnd: 0 }}
            />
          </Space>
        </Card>
        <div style={{ flex: 1, minWidth: 0 }}>
          {hint && <Alert type="warning" showIcon message={hint} style={{ marginBottom: 16 }} />}
          <Outlet context={{ dataset: data }} />
        </div>
      </Flex>
    </PageContainer>
  );
}
