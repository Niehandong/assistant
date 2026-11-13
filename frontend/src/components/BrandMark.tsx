import type { CSSProperties } from 'react';

/** 书脊标识：几本高低不一的书竖排；颜色取书脊色板 */
const BOOKS: { x: number; h: number; fill: string }[] = [
  { x: 2, h: 22, fill: '#0E6E6E' },
  { x: 10, h: 28, fill: '#3D5A80' },
  { x: 18, h: 19, fill: '#8A6D1F' },
  { x: 26, h: 25, fill: '#7B4B6A' },
];

export default function BrandMark({ size = 24, style }: { size?: number; style?: CSSProperties }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 34 32"
      role="img"
      aria-label="知识库平台"
      style={style}
    >
      {BOOKS.map((b) => (
        <rect key={b.x} x={b.x} y={30 - b.h} width={6} height={b.h} rx={1} fill={b.fill} />
      ))}
      <rect x={0} y={30} width={34} height={2} rx={1} fill="#E2E7E4" />
    </svg>
  );
}
