#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Independent analytic color bars through a newly linked native scope client.

Creates lossless RGB16 SDR/PQ/HLG videos. Computes expected bin positions in
Python without using the C implementation. Checks all three plots of every
backend the client reports (gpu with -DSCOPE_GPU, cpu always), plus native
seek/unload checks; permits one bin for RGB conversion/float boundary rounding.
With --compare, also reports how closely the GPU and CPU plots of real video
agree when both analyse the same raster size.
"""
import argparse
import json
import math
import os
from pathlib import Path
import struct
import subprocess


def nits(e,tf):
    if not e: return 0
    if tf == 'pq':
        p=e**(32/2523)
        return 10000*(max(p-3424/4096,0)/(2413/128-2392/128*p))**(16384/2610)
    if tf == 'hlg':
        a=.17883277;b=1-4*a;c=.5-a*math.log(4*a)
        return 1000*((e*e/3 if e<=.5 else (math.exp((e-c)/a)+b)/12))**1.2
    return e


def expected(bars,w,h,tf):
    kr,kb=(.2126,.0722) if tf=='sdr' else (.2627,.0593)
    peak=10000 if tf=='pq' else 1000
    def level(v):
        if tf!='sdr':v=(math.log10(max(.1,min(v,peak)))+1)/(math.log10(peak)+1)
        return int(max(0,min(v,1))*(h-1))
    wave=set();parade=set();vec=set();cw=(w-6)//4
    for x in range(16):
        r,g,b=bars[x//2];rn,gn,bn=(nits(v,tf) for v in (r,g,b))
        y=kr*rn+(1-kr-kb)*gn+kb*bn
        wave.add((x*w//16,h-1-level(y)))
        for c,value in enumerate((rn,gn,bn,y)):
            parade.add((c*(cw+2)+x*cw//16,h-1-level(value)))
        y=kr*r+(1-kr-kb)*g+kb*b
        vec.add((int(h/2+(b-y)/(2*(1-kb))*h*.9),int(h/2-(r-y)/(2*(1-kr))*h*.9)))
    return wave,parade,vec


def verify(actual,expected,label):
    # One-pixel tolerance handles bin boundaries, not missing/extra traces.
    def close(a,b):return abs(a[0]-b[0])<=1 and abs(a[1]-b[1])<=1
    missing=[p for p in expected if not any(close(p,q) for q in actual)]
    extra=[p for p in actual if not any(close(p,q) for q in expected)]
    if missing or extra:raise AssertionError(f'{label}: missing={missing[:10]} extra={extra[:10]}')


def occupancy(data,width):
    return {(i%width,i//width) for i in range(len(data)//4) if data[i*4+3]}


# Measured 0.73-0.91 (waveform/parade) and 0.50-0.70 (vectorscope) on UHD
# test signals; chroma upsampling differs most between libplacebo and swscale.
MIN_AGREEMENT={'waveform':0.6,'parade':0.6,'vectorscope':0.4}


def intensity(data):
    return [max(data[i:i+3]) for i in range(0,len(data),4)]


def covered(a,b,width):
    height=len(a)//width;total=hit=0
    for y in range(height):
        for x in range(width):
            v=a[y*width+x]
            if not v:continue
            near=max(b[yy*width+xx] for yy in range(max(0,y-1),min(height,y+2))
                                    for xx in range(max(0,x-1),min(width,x+2)))
            total+=v;hit+=min(v,near)
    return hit/max(1,total)


def compare(client,video,output):
    # Same raster size for both backends; the GPU averages with libplacebo's
    # box filter, the CPU with swscale's area filter, so edges differ slightly.
    prefix=output/('compare-'+video.stem)
    env={**os.environ,'SCOPE_ANALYSIS':'720'}
    r=subprocess.run([str(client),str(video),str(prefix),'no','720'],capture_output=True,text=True,check=True,env=env)
    result=json.loads(r.stdout)
    if not (result.get('gpu') and result.get('cpu')):raise AssertionError('needs both backends: '+r.stdout)
    agreement={}
    w,h=result['gpu']['w'],result['gpu']['h']
    for name in ('waveform','parade','vectorscope'):
        width=h if name=='vectorscope' else w
        g,c=(intensity((output/f'{prefix.name}-{b}-{name}.bgra').read_bytes()) for b in ('gpu','cpu'))
        # Share of each plot's intensity present in the other within one bin.
        score=min(covered(g,c,width),covered(c,g,width))
        agreement[name]=round(score,4)
        if score < MIN_AGREEMENT[name]:raise AssertionError(f'{video.name} {name}: {score}')
    return {'agreementWithinOneBin':agreement,'timingMS':result['timingMS']}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('client',type=Path)
    p.add_argument('output',type=Path);p.add_argument('--ffmpeg',type=Path,required=True)
    p.add_argument('--compare',type=Path,action='append',default=[],help='video for GPU/CPU agreement')
    a=p.parse_args()
    a.output.mkdir(parents=True,exist_ok=False)
    bars=[(0,0,0),(1,1,1),(1,0,0),(0,1,0),(0,0,1),(0,1,1),(1,0,1),(1,1,0)]
    results=[]
    for label in ('sdr','pq','hlg','pq-bars','hlg-bars'):
        tf=label.split('-')[0]
        # HDR neutral values exercise absolute luminance, not just black/peak.
        colors=bars if tf=='sdr' or label.endswith('-bars') else [(v,v,v) for v in (0,.125,.25,.5,.625,.75,.875,1)]
        colors=[tuple(round(v*65535)/65535 for v in rgb) for rgb in colors]
        raw=a.output/(label+'.rgb');video=a.output/(label+'.mkv')
        raw.write_bytes(b''.join(struct.pack('<HHH',*(round(v*65535) for v in colors[x//2])) for y in range(16) for x in range(16)))
        subprocess.run([str(a.ffmpeg),'-v','error','-f','rawvideo','-pixel_format','rgb48le','-video_size','16x16','-framerate','2','-i',str(raw),'-vf','loop=loop=3:size=1:start=0,format=gbrp16le,setparams=range=full:color_primaries='+('bt709' if tf=='sdr' else 'bt2020')+':color_trc='+{'sdr':'iec61966-2-1','pq':'smpte2084','hlg':'arib-std-b67'}[tf],
                        '-c:v','ffv1','-pix_fmt','gbrp16le','-color_primaries','bt709' if tf=='sdr' else 'bt2020',
                        '-color_trc',{'sdr':'iec61966-2-1','pq':'smpte2084','hlg':'arib-std-b67'}[tf],'-colorspace','rgb',str(video)],check=True)
        prefix=a.output/label
        r=subprocess.run([str(a.client),str(video),str(prefix),'no','64'],capture_output=True,text=True,check=True)
        result=json.loads(r.stdout)
        backends=[b for b in ('gpu','cpu') if result.get(b)]
        if not backends:raise AssertionError(result)
        for backend in backends:
            meta=result[backend];w,h=meta['w'],meta['h']
            if meta['transfer'] != {'sdr':'srgb','pq':'pq','hlg':'hlg'}[tf]:raise AssertionError(meta)
            if meta['primaries'] != ('bt.709' if tf=='sdr' else 'bt.2020'):raise AssertionError(meta)
            for name,points in zip(('waveform','parade','vectorscope'),expected(colors,w,h,tf)):
                data=(a.output/f'{label}-{backend}-{name}.bgra').read_bytes();width=h if name=='vectorscope' else w
                verify(occupancy(data,width),points,f'{backend} {tf} {name}')
        results.append({'case':label,'signalBins':'passed','backends':backends,**result})
    for video in a.compare:
        results.append({'case':'compare '+video.name,**compare(a.client,video,a.output)})
    (a.output/'acceptance.json').write_text(json.dumps(results,indent=2)+'\n')
    print(json.dumps(results,indent=2))

if __name__=='__main__':main()
