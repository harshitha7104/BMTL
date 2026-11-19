import React from 'react';

// Small, safe Markdown renderer: builds React elements (never injects HTML).
// Supports headings, paragraphs, bullet/numbered lists, block quotes, fenced code, tables,
// **bold**, _italic_, `code` and [links](https://...).
// Backslash escapes (\[ \] \* \_ \` \( \) \< \> \# \| \\) are shown as plain characters: the server escapes untrusted
// text (uploaded documents, web pages, transcripts, sample labels) this way so it can never become a link (audit N-05).

function renderInline(text: string, keyBase: string): React.ReactNode[] {
  const parts = text.split(
    /(\\[\\`*_[\]()<>#|]|\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\(https?:\/\/[^)\s]+\)|(?<![\w])_[^_\n]+_(?![\w])|(?<![\w*])\*[^*\s][^*\n]*\*(?![\w*]))/g
  );
  return parts.map((p, i) => {
    const key = `${keyBase}-${i}`;
    if (!p) return null;
    if (p.length === 2 && p[0] === '\\') return <React.Fragment key={key}>{p[1]}</React.Fragment>;
    if (p.startsWith('**') && p.endsWith('**')) return <strong key={key} className="font-semibold text-ace-ink">{p.slice(2, -2)}</strong>;
    if (p.startsWith('`') && p.endsWith('`'))
      return <code key={key} className="px-1 py-0.5 rounded bg-ace-stone font-mono text-[0.85em]">{p.slice(1, -1)}</code>;
    const link = /^\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)$/.exec(p);
    if (link)
      return <a key={key} href={link[2]} target="_blank" rel="noreferrer noopener" className="text-ace-terracotta underline underline-offset-2">{link[1]}</a>;
    if (((p.startsWith('_') && p.endsWith('_')) || (p.startsWith('*') && p.endsWith('*'))) && p.length > 2)
      return <em key={key}>{p.slice(1, -1)}</em>;
    return <React.Fragment key={key}>{p}</React.Fragment>;
  });
}

export default function Markdown({ text }: { text: string }) {
  const lines = text.split('\n');
  const blocks: React.ReactNode[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    // Fold-out: "<details><summary>Title</summary>" ... "</details>" (exact pattern only; rendered as React, never as HTML)
    const fold = /^<details><summary>([^<]{1,120})<\/summary>\s*$/.exec(line.trim());
    if (fold) {
      const inner: string[] = [];
      i++;
      while (i < lines.length && lines[i].trim() !== '</details>') inner.push(lines[i++]);
      i++;
      blocks.push(
        <details key={`d${i}`} className="rounded-xl border border-ace-line bg-white/60 px-3 py-2 text-sm">
          <summary className="cursor-pointer select-none text-ace-muted hover:text-ace-ink">{fold[1]}</summary>
          <div className="mt-2"><Markdown text={inner.join('\n')} /></div>
        </details>
      );
      continue;
    }
    if (line.startsWith('```')) {
      const code: string[] = [];
      i++;
      while (i < lines.length && !lines[i].startsWith('```')) code.push(lines[i++]);
      i++;
      blocks.push(
        <pre key={`c${i}`} className="bg-ace-night text-ace-stone font-mono text-xs p-3 rounded-xl overflow-x-auto">{code.join('\n')}</pre>
      );
      continue;
    }
    if (line.trim().startsWith('|')) {
      const rows: string[][] = [];
      while (i < lines.length && lines[i].trim().startsWith('|')) {
        const cells = lines[i].trim().replace(/^\||\|$/g, '').split('|').map(c => c.trim());
        if (!cells.every(c => /^:?-{2,}:?$/.test(c))) rows.push(cells);
        i++;
      }
      blocks.push(
        <div key={`t${i}`} className="overflow-x-auto">
          <table className="text-sm border-collapse my-1">
            <tbody>
              {rows.map((r, ri) => (
                <tr key={ri} className={ri === 0 ? 'font-semibold bg-ace-stone' : ''}>
                  {r.map((c, ci) => (
                    <td key={ci} className="border border-ace-line px-2.5 py-1.5 align-top">{renderInline(c, `t${ri}${ci}`)}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
      continue;
    }
    if (line.startsWith('>')) {
      const quote: string[] = [];
      while (i < lines.length && lines[i].startsWith('>')) quote.push(lines[i++].replace(/^>\s?/, ''));
      blocks.push(
        <blockquote key={`q${i}`} className="border-l-2 border-ace-terracotta/50 pl-3 text-ace-muted italic">
          {renderInline(quote.join(' '), `q${i}`)}
        </blockquote>
      );
      continue;
    }
    const heading = /^(#{1,4})\s+(.*)/.exec(line);
    if (heading) {
      const size = heading[1].length <= 2 ? 'text-base' : 'text-[0.95rem]';
      blocks.push(<p key={`h${i}`} className={`font-semibold text-ace-ink mt-3 ${size}`}>{renderInline(heading[2], `h${i}`)}</p>);
      i++;
      continue;
    }
    if (/^\s*([-*]|\d+\.)\s+/.test(line)) {
      const ordered = /^\s*\d+\./.test(line);
      const items: { depth: number; text: string }[] = [];
      while (i < lines.length && /^\s*([-*]|\d+\.)\s+/.test(lines[i])) {
        const m = /^(\s*)([-*]|\d+\.)\s+(.*)/.exec(lines[i])!;
        items.push({ depth: m[1].length >= 2 ? 1 : 0, text: m[3] });
        i++;
      }
      blocks.push(
        <ul key={`l${i}`} className="space-y-1">
          {items.map((it, k) => (
            <li key={k} className={`flex gap-2.5 ${it.depth ? 'ml-5' : ''}`}>
              <span className="text-ace-terracotta select-none mt-px">{ordered && !it.depth ? `${k + 1}.` : '•'}</span>
              <span className="min-w-0">{renderInline(it.text, `l${i}${k}`)}</span>
            </li>
          ))}
        </ul>
      );
      continue;
    }
    if (line.trim()) blocks.push(<p key={`p${i}`}>{renderInline(line, `p${i}`)}</p>);
    i++;
  }
  return <div className="space-y-2.5 text-[0.95rem] leading-7 text-ace-ink break-words">{blocks}</div>;
}
