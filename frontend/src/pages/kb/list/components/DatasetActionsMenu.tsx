import {
  DeleteOutlined,
  EllipsisOutlined,
  SettingOutlined,
  ShareAltOutlined,
} from '@ant-design/icons';
import { Button, Dropdown, type MenuProps } from 'antd';
import { useNavigate } from 'react-router-dom';
import { usePermission } from '@/access/usePermission';
import type { DatasetItem } from '@/services/types/kb-contract';
import { datasetActions } from '../logic';

interface Props {
  dataset: DatasetItem;
  onDelete: (d: DatasetItem) => void;
}

/** 卡片/列表行的“...”菜单；无任何可用操作时不渲染 */
export default function DatasetActionsMenu({ dataset, onDelete }: Props) {
  const can = usePermission();
  const navigate = useNavigate();
  const a = datasetActions(dataset, can);
  const items: MenuProps['items'] = [];
  if (a.canSettings) {
    items.push({
      key: 'settings',
      icon: <SettingOutlined />,
      label: '设置',
      onClick: () => navigate(`/kb/datasets/${dataset.id}/settings`),
    });
  }
  if (a.canAssign) {
    items.push({
      key: 'assign',
      icon: <ShareAltOutlined />,
      label: '分配',
      onClick: () => navigate(`/kb/datasets/${dataset.id}/assignments`),
    });
  }
  if (a.canDelete) {
    items.push({ type: 'divider' });
    items.push({
      key: 'delete',
      icon: <DeleteOutlined />,
      label: '删除',
      danger: true,
      onClick: () => onDelete(dataset),
    });
  }
  if (items.length === 0) return null;
  return (
    <Dropdown menu={{ items }} trigger={['click']}>
      <Button
        type="text"
        size="small"
        aria-label="更多操作"
        icon={<EllipsisOutlined />}
        onClick={(e) => e.stopPropagation()}
      />
    </Dropdown>
  );
}
