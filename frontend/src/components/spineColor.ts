/** 书脊色板（8 色，低饱和）：只用于知识库卡片色带与图标 */
export const SPINE_COLORS = [
  '#0E6E6E',
  '#3D5A80',
  '#7A5C3E',
  '#5B6C3A',
  '#7B4B6A',
  '#2F6F8F',
  '#8A6D1F',
  '#4E5D6C',
] as const;

/** 按图标名确定性取色：同名恒同色；空值与未知名按字符串哈希，不会抛错 */
export function spineColor(iconName?: string | null): string {
  const s = iconName ?? '';
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0;
  return SPINE_COLORS[h % SPINE_COLORS.length];
}
