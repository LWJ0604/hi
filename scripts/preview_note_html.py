"""Local reading preview of generated Markdown, not the actual Obsidian renderer."""
import argparse
import html
from pathlib import Path
import re
from urllib.parse import quote

STYLE='''body{font:15px/1.55 "Malgun Gothic","Noto Sans CJK JP",sans-serif;background:#f6f7f9;color:#172033;margin:0}main{max-width:820px;margin:20px auto;background:white;padding:28px 34px;border-radius:14px}h1{font-size:25px;margin:0 0 16px}h2{font-size:19px;margin:18px 0 8px}p{margin:8px 0}img{display:block;max-width:100%;height:auto;margin:10px 0}table{border-collapse:collapse;font-size:13px;margin:12px 0;width:100%}th,td{border:1px solid #dbe0e8;padding:7px;text-align:left}details{border:1px solid #dce2eb;border-radius:8px;margin:10px 0;padding:10px;background:#f8fafc}summary{font-weight:600;cursor:pointer}pre{white-space:pre-wrap;font-size:12px}a{color:#2269b5}aside{font-size:12px;color:#667084}.warning{border-left:4px solid #b17a08;background:#fff8e9;padding:10px 16px;margin:14px 0}ul{padding-left:24px}'''


def render(text):
    def inline(text):
        text=html.escape(text)
        def wiki(m):
            body=m[2];path,sep,label=body.partition('|');url=quote(path)
            if m[1]:return f'<img src="{url}" width="{label if label.isdigit() else 640}" loading="lazy" alt="{html.escape(path)}">'
            return f'<a href="{url}">{label or path}</a>'
        text=re.sub(r'(!?)\[\[([^\]]+)\]\]',wiki,text)
        text=re.sub(r'\*\*(.+?)\*\*',r'<strong>\1</strong>',text)
        return text.replace('\\|','|')
    lines=text.splitlines();output=[];i=0
    if lines and lines[0]=='---':
        end=lines[1:].index('---')+1;props=lines[1:end]
        output.append('<details><summary>기존 분석 속성</summary><pre>'+html.escape('\n'.join(props))+'</pre></details>');i=end+1
    def blocks(lines):
        out=[];j=0
        while j<len(lines):
            line=lines[j]
            if line.startswith('> [!'):
                match=re.match(r'> \[!([^\]]+)\](-?)\s*(.*)',line)
                title=match[3];body=[];j+=1
                while j<len(lines) and lines[j].startswith('>'):
                    body.append(lines[j][2:] if lines[j].startswith('> ') else lines[j][1:]);j+=1
                content=blocks(body)
                out.append(('<details><summary>'+inline(title)+'</summary>'+content+'</details>') if match[2] else '<div class="warning"><strong>'+inline(title)+'</strong>'+content+'</div>');continue
            if line.startswith('```'):
                j+=1;code=[]
                while j<len(lines) and not lines[j].startswith('```'):code.append(lines[j]);j+=1
                out.append('<pre>'+html.escape('\n'.join(code))+'</pre>');j+=1;continue
            if line.startswith('|'):
                rows=[]
                while j<len(lines) and lines[j].startswith('|'):
                    if not re.fullmatch(r'[| :\-]+',lines[j]):rows.append(re.split(r'(?<!\\)\|',lines[j].strip('|')))
                    j+=1
                out.append('<table>'+''.join('<tr>'+''.join(('<th>' if k==0 else '<td>')+inline(value.strip())+('</th>' if k==0 else '</td>') for value in row)+'</tr>' for k,row in enumerate(rows))+'</table>');continue
            if line.startswith('#'):
                match=re.match(r'(#+)\s+(.*)',line)
                if match:out.append(f'<h{len(match[1])}>'+inline(match[2])+f'</h{len(match[1])}>')
            elif line.startswith('- '):out.append('<p>• '+inline(line[2:])+'</p>')
            elif line.strip():out.append('<p>'+inline(line)+'</p>')
            j+=1
        return ''.join(out)
    output.append(blocks(lines[i:]))
    return '<!doctype html><html lang="ko"><meta charset="utf-8"><title>연구 노트 읽기 미리보기</title><style>'+STYLE+'</style><main><aside>Markdown 읽기 미리보기 · 실제 Obsidian 화면 검증과 구분합니다.</aside>'+''.join(output)+'</main></html>'


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('note');parser.add_argument('output');args=parser.parse_args()
    Path(args.output).write_text(render(Path(args.note).read_text(encoding='utf-8-sig')),encoding='utf-8')
