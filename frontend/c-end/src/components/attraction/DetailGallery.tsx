'use client';

/**
 * 景点图集。
 *
 * 单图时直接铺满，多图时首图大图 + 缩略图条。
 * **无图时降级为渐变背景**，与卡片一致——不能因为是详情页就空一块。
 */
import { useState } from 'react';

export interface DetailGalleryProps {
  name: string;
  imageUrls: string[];
}

function gradientFor(name: string): string {
  let hash = 0;
  for (let i = 0; i < name.length; i += 1) {
    hash = (hash * 31 + name.charCodeAt(i)) % 360;
  }
  return `linear-gradient(135deg, hsl(${hash}, 70%, 75%), hsl(${(hash + 40) % 360}, 70%, 65%))`;
}

export function DetailGallery({ name, imageUrls }: DetailGalleryProps) {
  const [activeIndex, setActiveIndex] = useState(0);

  if (imageUrls.length === 0) {
    return (
      <div
        style={{
          width: '100%',
          aspectRatio: '16 / 9',
          borderRadius: 12,
          background: gradientFor(name),
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          color: '#fff',
          fontSize: 48,
          fontWeight: 600,
          opacity: 0.9,
        }}
        role="img"
        aria-label={`${name}（暂无图片）`}
      >
        {name.slice(0, 2)}
      </div>
    );
  }

  const current = imageUrls[Math.min(activeIndex, imageUrls.length - 1)];

  return (
    <div>
      <div
        style={{
          width: '100%',
          aspectRatio: '16 / 9',
          borderRadius: 12,
          overflow: 'hidden',
          background: '#f5f5f5',
        }}
      >
        {/* 外链图片域名不固定，next/image 需逐个配置 remotePatterns */}
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={current}
          alt={name}
          style={{ width: '100%', height: '100%', objectFit: 'cover' }}
        />
      </div>

      {imageUrls.length > 1 && (
        <div
          style={{
            display: 'flex',
            gap: 8,
            marginTop: 10,
            overflowX: 'auto',
            paddingBottom: 4,
          }}
        >
          {imageUrls.map((url, index) => (
            <button
              key={`${url}-${index}`}
              type="button"
              onClick={() => setActiveIndex(index)}
              aria-label={`查看第 ${index + 1} 张图片`}
              aria-pressed={index === activeIndex}
              style={{
                flexShrink: 0,
                width: 96,
                height: 64,
                padding: 0,
                border:
                  index === activeIndex
                    ? '2px solid #1677ff'
                    : '2px solid transparent',
                borderRadius: 6,
                overflow: 'hidden',
                cursor: 'pointer',
                background: 'none',
              }}
            >
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={url}
                alt=""
                style={{ width: '100%', height: '100%', objectFit: 'cover' }}
              />
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
