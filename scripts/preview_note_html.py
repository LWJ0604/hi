"""Local reading preview of generated Markdown, not the actual Obsidian renderer."""
import argparse
import html
from pathlib import Path
import re
from urllib.parse import quote

STYLE='''body{font:15px/1.55 "Malgun Gothic","Noto Sans CJK JP",sans-serif;background:#f6f7f9;color:#172033;margin:0}main{max-width:820px;margin:20px auto;background:white;padding:28px 34px;border-radius:14px}h1{font-size:25px;margin:0 0 16px}h2{font-size:19px;margin:18px 0 8px}p{margin:8px 0}img{display:block;max-width:100%;height:auto;margin:10px 0}table{border-collapse:collapse;font-size:13px;margin:12px 0;width:100%}th,td{border:1px solid #dbe0e8;padding:7px;text-align:left}details{border:1px solid #dce2eb;border-radius:8px;margin:10px 0;padding:10px;background:#f8fafc}summary{font-weight:600;cursor:pointer}pre{white-space:pre-wrap;font-size:12px}a{color:#2269b5}aside{font-size:12px;color:#667084}.warning{border-left:4px solid #b17a08;background:#fff8e9;padding:10px 16px;margin:14px 0}ul{padding-left:24px}'''


def render(text):
    def inline(text):
        tokens=[]
        def token(value):
            tokens.append(value)
            return '\x00'+str(len(tokens)-1)+'\x00'
        def markdown(m):
            path=m[3].strip('<>')
            if re.match(r'(?i)(?:javascript|data|vbscript):',path):return html.escape(m[0])
            url=html.escape(quote(path,safe='/#:'),quote=True)
            label=html.escape(m[2])
            return token(f'<img src="{url}" loading="lazy" alt="{label}">'
                         if m[1] else f'<a href="{url}">{label}</a>')
        text=re.sub(r'(!?)\[([^\[\]]+)\]\((<[^>]+>|[^)]+)\)',markdown,text)
        text=re.sub(r'<a id="([a-z][a-z0-9-]*)"></a>',lambda m:token('<a id="'+m[1]+'"></a>'),text)
        text=re.sub(r'`([^`]+)`',lambda m:token('<code>'+html.escape(m[1])+'</code>'),text)
        text=html.escape(text)
        def wiki(m):
            body=m[2];path,sep,label=body.partition('|');url=quote(path)
            if m[1]:return f'<img src="{url}" width="{label if label.isdigit() else 640}" loading="lazy" alt="{html.escape(path)}">'
            return f'<a href="{url}">{label or path}</a>'
        text=re.sub(r'(!?)\[\[([^\]]+)\]\]',wiki,text)
        text=re.sub(r'\*\*(.+?)\*\*',r'<strong>\1</strong>',text)
        for index,value in enumerate(tokens):text=text.replace('\x00'+str(index)+'\x00',value)
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
    return '<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>연구 노트 읽기 미리보기</title><style>'+STYLE+'code{font-size:12px;overflow-wrap:anywhere}main{overflow-wrap:anywhere}summary:focus-visible,a:focus-visible{outline:2px solid #2269b5}@media(max-width:600px){main{margin:0;padding:20px 16px;border-radius:0}h1{font-size:22px}table{display:block;overflow:auto}}</style><main><aside>Markdown 읽기 미리보기 · 실제 Obsidian 화면 검증과 구분합니다.</aside>'+''.join(output)+'</main></html>'


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('note');parser.add_argument('output');args=parser.parse_args()
    Path(args.output).write_text(render(Path(args.note).read_text(encoding='utf-8-sig')),encoding='utf-8')
