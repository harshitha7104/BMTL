// ACE Green-style mark: concentric arcs in terracotta.
export default function BrandMark({ size = 28, tile = true }: { size?: number; tile?: boolean }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true" className="shrink-0">
      {tile && <rect width="32" height="32" rx="8" fill="#a3563a" />}
      <path
        d="M9 23a10 10 0 0 1 14-14M12.5 23a6 6 0 0 1 8.5-8.5M16 23a2 2 0 0 1 3-3"
        fill="none"
        stroke={tile ? '#f6efe8' : '#a3563a'}
        strokeWidth="2.2"
        strokeLinecap="round"
      />
    </svg>
  );
}
