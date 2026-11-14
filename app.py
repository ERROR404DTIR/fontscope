#!/usr/bin/env python3
"""FontScope — inspect TrueType/OpenType SFNT fonts. Python 3.9+, stdlib only."""
import argparse, json, struct, sys
from pathlib import Path
def u16(b,o): return struct.unpack_from(">H",b,o)[0]
def u32(b,o): return struct.unpack_from(">I",b,o)[0]
def parse(path):
    data=Path(path).read_bytes()
    if len(data)<12: raise ValueError("File is too small to be an SFNT font")
    sig=data[:4]
    if sig==b"ttcf": raise ValueError("TTC collections are not supported yet; extract a TTF/OTF face first")
    if sig not in (b"\x00\x01\x00\x00",b"OTTO",b"true"): raise ValueError("Unsupported font signature (expected TTF or OTF)")
    count=u16(data,4); tables={}
    if 12+count*16>len(data): raise ValueError("Truncated table directory")
    for i in range(count):
        off=12+i*16; tag=data[off:off+4].decode("ascii","replace"); start=u32(data,off+8); size=u32(data,off+12)
        if start+size>len(data): raise ValueError("Table outside file: "+tag)
        tables[tag]=(start,size)
    def table(tag):
        if tag not in tables: return b""
        a,n=tables[tag]; return data[a:a+n]
    names={}
    nt=table("name")
    if nt and len(nt)>=6:
        count=u16(nt,2); start=u16(nt,4)
        ids={1:"family",2:"subfamily",4:"full_name",6:"postscript_name",16:"typographic_family",17:"typographic_subfamily"}
        for i in range(count):
            o=6+i*12
            if o+12>len(nt): break
            platform,encoding,language,nid,length,offset=struct.unpack_from(">6H",nt,o)
            if nid not in ids or start+offset+length>len(nt): continue
            raw=nt[start+offset:start+offset+length]
            try: value=raw.decode("utf-16-be" if platform in (0,3) else "mac_roman","replace").strip("\x00 ")
            except Exception: continue
            if value and ids[nid] not in names: names[ids[nid]]=value
    cmap=table("cmap"); codepoints=set()
    if cmap and len(cmap)>=4:
        n=u16(cmap,2)
        for i in range(n):
            o=4+i*8
            if o+8>len(cmap): break
            suboff=u32(cmap,o+4)
            if suboff+2>len(cmap): continue
            fmt=u16(cmap,suboff)
            if fmt==12 and suboff+16<=len(cmap):
                groups=u32(cmap,suboff+12)
                for j in range(min(groups,20000)):
                    q=suboff+16+j*12
                    if q+12>len(cmap): break
                    first,last,_=struct.unpack_from(">III",cmap,q)
                    if last-first<200000: codepoints.update(range(first,last+1))
            elif fmt==4 and suboff+14<=len(cmap):
                length=u16(cmap,suboff+2); endbase=suboff+length
                seg=u16(cmap,suboff+6)//2
                endpos=suboff+14; startpos=endpos+2*seg+2; delta_pos=startpos+2*seg; range_pos=delta_pos+2*seg
                if endbase<=len(cmap) and seg<10000:
                    for j in range(seg):
                        first=u16(cmap,startpos+2*j); last=u16(cmap,endpos+2*j); delta=struct.unpack_from(">h",cmap,delta_pos+2*j)[0]; ro=u16(cmap,range_pos+2*j)
                        for cp in range(first,min(last,65534)+1):
                            if ro==0: glyph=(cp+delta)&65535
                            else:
                                pos=range_pos+2*j+ro+2*(cp-first)
                                glyph=u16(cmap,pos) if pos+2<=endbase else 0
                                if glyph: glyph=(glyph+delta)&65535
                            if glyph: codepoints.add(cp)
    os2=table("OS/2"); weight=u16(os2,4) if len(os2)>=6 else None
    return {"file":str(path),"bytes":len(data),"format":"OpenType CFF" if sig==b"OTTO" else "TrueType","family":names.get("typographic_family",names.get("family","Unknown")),"subfamily":names.get("typographic_subfamily",names.get("subfamily","Regular")),"full_name":names.get("full_name",""),"postscript_name":names.get("postscript_name",""),"weight_class":weight,"table_count":count,"tables":sorted(tables),"unicode_codepoints":len(codepoints),"unicode_blocks":blocks(codepoints)}
def blocks(cps):
    ranges=[(0x20,0x7e,"Basic Latin"),(0x80,0xff,"Latin-1 Supplement"),(0x100,0x24f,"Latin Extended"),(0x370,0x3ff,"Greek"),(0x400,0x52f,"Cyrillic"),(0x590,0x5ff,"Hebrew"),(0x600,0x6ff,"Arabic"),(0x750,0x77f,"Arabic Supplement"),(0x8a0,0x8ff,"Arabic Extended-A"),(0x900,0x97f,"Devanagari"),(0x2000,0x206f,"General Punctuation"),(0x20a0,0x20cf,"Currency Symbols"),(0x1f300,0x1f5ff,"Misc Symbols and Pictographs")]
    return [name for a,b,name in ranges if any(a<=x<=b for x in cps)]
def main():
    p=argparse.ArgumentParser(description="Inspect TTF/OTF font metadata and Unicode coverage"); s=p.add_subparsers(dest="cmd",required=True)
    for cmd in ("inspect","scan"):
        q=s.add_parser(cmd); q.add_argument("path"); q.add_argument("--json"); q.add_argument("--css")
    a=p.parse_args(); root=Path(a.path); paths=[root] if root.is_file() else sorted([*root.rglob("*.ttf"),*root.rglob("*.otf")]) if root.is_dir() else []
    if not paths: print("No TTF/OTF fonts found.",file=sys.stderr); return 2
    results=[]
    for f in paths:
        try:
            r=parse(f); results.append(r); print(f"{r['family']} / {r['subfamily']} — {r['unicode_codepoints']} codepoints — {f}")
        except Exception as e: print(f"[ERROR] {f}: {e}")
    if a.json: Path(a.json).write_text(json.dumps(results,indent=2,ensure_ascii=False),encoding="utf-8")
    if a.css:
        lines=[]
        for r in results:
            family=r["family"].replace("\\","\\\\").replace("'","\\'")
            lines += ["@font-face {",f"  font-family: '{family}';",f"  src: url('{Path(r['file']).name}') format('{'opentype' if r['format']=='OpenType CFF' else 'truetype'}');",f"  font-weight: {r['weight_class'] or 400};","  font-style: normal;","}",""]
        Path(a.css).write_text("\n".join(lines),encoding="utf-8")
    return 0
if __name__=="__main__": sys.exit(main())