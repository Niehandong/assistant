import type { CSSProperties } from 'react';
import { DATASET_ICONS, DEFAULT_DATASET_ICON } from './datasetIcons';

export default function DatasetIcon({
  name,
  style,
}: {
  name?: string | null;
  style?: CSSProperties;
}) {
  const Icon = DATASET_ICONS[name ?? ''] ?? DATASET_ICONS[DEFAULT_DATASET_ICON];
  return <Icon style={style} />;
}
