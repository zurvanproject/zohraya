"""Install only the bounded owner-requested Tadash research session on 2026-11-08."""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import ssl
import subprocess
import sys
import time
from email.utils import parsedate_to_datetime
from urllib.request import build_opener, Request, HTTPSHandler, HTTPRedirectHandler, ProxyHandler
import uuid
import zlib

PACK = 'c-pmn3v=5zlJH;QdTvUjP0^D4lD*N)c@k&Fw~3Q-ytBKX?P5_BWb;Ci3Lj29Q~B@L4*&#6%1-v~ODd5>0?kIF(JwTbe{L0`6j2f12kXbJldT*2`#Q;zN;u_XR^5v#iJf(k|F?)M{G5w2aNcFYNwS4l3-~Xqd}kplQLLa_iOu8uJ};oPD4a6QtAL^2WXWoc*Q4TY9Tlax$(BXFg4SsYz>_>H9ogb#US|MMHn@+<`!t!Wo8^5pIXKkN{=3XG*>DwA_o`JalGJz7{7yH_OWAA<%?x<&;iqm?MA;%=$%bVWRWu@v*h)m15C1Qc2p%e%Wuh+fwMZXe=(61fUV2ZLH0XyYts@+!6P3;b_Wtnlx3jmW&dj;l%A&F^qQ__`9z>R8cf*G<QtZQ<cUR%dcYnXQf>!&}o9zAh#RvHM=S}9oAL!RS8)ook>%?(yw)Xb+=KB+I98V7p=A)x=Je`i?Lvgq~KAawnq9_svB3>Ns-)#8|r{~Yj)_5E(_YRKtM)Sj?c)UDb983-;V=<0LqrLI*JYG!Wz0ve&c{mm0<^E`Ye>6Fa7R&iE-k%=CW5D0@6`FeN4U$KP2lM^o!{umsJR0vs@pLqbCkJ9Wo*zx72hq{~p%7xSceEMFo2}!6MI0?fd@$NS-am?t4-TWre0sQ?ilfCeiYJrFJU)sh%NPi<HwL68<I(;c0FMrqVlfwt;@6w(<-3ckvwvP8X{&mj3ilyUm%JOA>4jK2@x6#YhGkwCu_#^dgz;MDg_A`q;X7{VJL1b4m{}}5SRfA0Rsc(B)wISxi>Qj=NyvC^7%r1kgrOIFPOAG50lD~}7Zf5|g!9J=9|b?wX%q{04qS0l+yF*fzC%CYo7aF&mU4Z#_z*9+7he|1ohU2UbN({Z*qzuUEuy3p&hIcu;;bn00;Z?VR9i=h2!}_00)%&VXvhX_%4FpxuxPU~sUCeNuB&{xgr$-%#O!7ZR#H(R%EkR-b-$VgM<e(y;`~7rk6~PkSuj-;!Y(P0$5=zI93hMj@8U>+_481IHAX|71G*l@k1@=o*US>E<c~Nlu*mO(yLT`$C*=p{LzS=L_PVZ|?YV#sV%q@$2x362ov7mPK$B#d099bXbs8aks$?aCE(&7p24g*9{_q`5qnZAO!y?pPNU}L1h3Oat{fs{c#sE%1qL~!*0Yw0aiwwx?1J?O^M%0=iweTm*8;Cc47F-;UY{sGMKg|>p*i@6V62Theumm=TZ)uVVi}VV&k9-LQSyiH}Dz0y~s{Cf__QavDKrZ+}Gg9Dm@I$!$SMFShsxC4Rb6bo|SfbS6@4I8*otv#SJc+Jycl;T~s5e?v<CbAmF${i8a3?C4@1P8TM!@71%=n_eVKZQ_1AdugQ5q6;8gvYjeQg%W`u?#@a!^W-E-FUFem^+xL3`E}Ylm`;E5CGL&83gTT%<)yCyI-_EQt+qo(s`16SK5r!shDCDS#piH#nTaign$|-Zp~T*&BP#k4~dpyzO9byz4d>hGQVgfn<-W0Lg<hdEL9nJ(@|$G<tR6B#p;ogmSA!c?yJjWP1WMD5-p2m$<M<whT%XQF(^ri&CdRu|zC;5A$=Mrwa%F3lzYAfXG}F(PvPYpoJrZl$0iP5S|rN43uyxRsffX49{64WejX4kiyVk!+eDrKLcY&EiM=uj6RMskpDO|hgpRu3nf4nKRVG8>=h?+kfS81Ig&mq5+>bkBZgQMAgM?|1bguB0RF+E4UU0ofhm?ik^u_>gkU<|*0kRV#*=M^(=-L6EBOO(vP5U__Vl0O<@ty6i(kVJXQ0$xeQ0_RLm}~?3lQCw2K?ZkEMV`?PX88O{dRfw;kS2hUbPm#0c|)ArrW^h?l>53?!U{=@OC;)@NN&f0<A&-4-@9f(faza9%8L=06xg_iiXAFRJL!R;Zy+2mM}=owL_SLsn;GCvo<_7`r^Wbp=k;Hz0K%&I}F6LJMo$jJj)ZD-s4dlFwHN(-Jm;Ln!{3;@XzZ37SwCd`@(&utFP7w$U88*1&F+vCSw<D!^uIkMw{PNqs_z}tb+&99mJTWbfctY57a|zP@0=Mu%42Qqp}oWIjg5!YpH*WdPst5T^(6nqcnA^>z0tdZEG=>LO53}>vpcyBYpLhTTf}GD86SVzed1~e!6W#p;csHciYx&WNU<)2B<v@f`FzZFnF22;WarIk70AOnI4<sCz@~_okhAOWLlr7A^N1uin0n(YyxX6YL;>#nWm&hS>wX;Q*@wJr-?!<4cDBZ^s*eJxLZKe6N><BXv6iO&JrNq${hxy2`rS+gjGst*lM0(YR=J|{nUbnYx5yEeR*~M?&5>*d=!tfPpG_2^F0UReu2>ypj+Hh;D`m9yCDn{W*R7(WMQTO(<HM)7+lf^byB=}2g@HCJOpomnwcnqc^YLOmA(0c^BVlx{BujWt;;0Mv*BF<fF7M?QdLMcc>cXW?G<H=g(G#Blh;+8uVCRd>Laec_)dnjc?iThDZ$<-39+5=2>)~jLfFQLE8!f(_jwL8LU3S^zQSr2OeV(a=f)`xj@tqZAD$^uGOlIbH8L~M6<9Y8>ncfsgTr-^e*vaeD`ySnCE0`V2~QzE;L~+{D@_O-lXAPHAvlKxio$|A{285)2X6Gdj&8es8C=99k}UC688dkmrHF=%F{t?>M!@T%Z=v)=QhGeGw8iHlXQlzB1}Z1uuwBPp{76xu69W&pH7E|CQF}8KTvh;v`47Ce7Y48LI)mO#Uy1+D3`K}bkoW<f#RL>(nUP@)Gn?URrg^zWR9Ji@<zsUh0nv4u2$DAVMOn;vL4Esb3?v3qnw|qQ*5;UJ`K536Y_*+6bCLSoMh>dS&2FaqnmXJfbr>~Z8^grnHaA;f)B#lxgB@1(+&IAK1$yCLTYw`kkN_1dJ>|la5*xqbReE^H6GWZ`ee1|%<ZML?Z1yL5*eBA0CmeTy-F)ZJGeQn@om37DLQ&!CS2JpXB6OiZyG$^g1tsW6im6FLl~yEqU81|*wABtcUt$*=Z1of<WVwNoI>nPyEJf&&&AAjzZWlYyg+^k~&+Ex8;TNaTYE7-!H-~0$YbS&M?0I<z)JUzyK7;eYuQqf-0d8JVf@xqX1u%}nd71<NHy+v<XgD=?ur2dBm=_OV$K+WoDAGw2j>4RJI;b+81f!!#3^PPZQ2Q8HpcC#zx)=h{Wl+^w<Ych20Y_S6ou^6s7&z|%Nt_UHNf97C4-oh$)>ZI-p{QD#wmWvR^PqpD$L+;vuhiE1GnI(VS^h?z`&NarEb>1{U|QP5fTbF;C~mu9#-Lkb{Qt{nJIfG<X#kf<Dhqq_n6x1s%~LeIGq7n~H`y5zeu)%|BCA&db%iSdd%eLVT+nO{vk)h58;$1Jx~f%}1a_UA03tq_dTKV%!Ul9yi{V((n)n-OFG<?r)15uiraQ?t8!#h}C0x=>&}3gl5$@1Bnz0$sCMltSWF2<y5Ub!VmYoQh@OoCHH|v3vqW(q3GC{@b3chqS=n^5*7V_LVtnv^k8&>xq-tX>1!Mc^_6v3c$fYlM=a6|On!scPD5%3Nw15?t|zKa!FS_7@xQ76OTVQXUMxT63JZ}h;}S3SUQM+X#)xW-P-kItc-0i+DAr72I>4&JA!+ezB<h6_t}lh!x&e9jVg$A>Vqec#!e03yeSBkwx-asRf5g(b@)2%GB(OHaF8EamCpJtBW+U)pmn=+_B6cYlhHh2bBALozvlZ+la?d@!CMCeuDlz8MwGY4N>SML40n4@BNCkdhbyKIu0(4j~B1RZ<ZL{`v9b;d;b2(ntTHz02^m!*O84tOeU?V8L?4y4l$)L8HV`LCapwN)5|+4!@J?uOJ1%&L9W>b6$MJ2p3yholO~7D4NS?p&<4WAfXM$f}UV)1j*?}!wIH>W4w}0x&u-3Cc&+9SU=6mB-6+Qr04wW6R3u9RI(GDip*VKH$L~Rx1%m~TyD5GF&C*6c?yggg13!GZ5l?{po*O|y5@qWEg<9t7xyepdkuFzgEWs8CEeo9B7CX~21337J7jjVRaeX5^k&Ozj5oKC0d2*6v@0a{A%UX^7Fw2U-{GT&KaM7gfOc88KnkEu#awy|9qhrO{W5Z1%&bN)%s8`YCwBLo5<q<gC?u%ZNa_?K7RkEe9Vd;PEwl?`6RKXVV4~bb0v)Toc+@1zKg+eR3CfxPH+;Z7FJM(Py@I<mpSyDSKmRNT@2MrMT}W7q_(-rbKN{N^_$&ran@w&Xzxh4P<M;4}_qEY_r3yK1)(tHznt&8eNV9%!ubYK(YYj@p4{5_;Mtq5*@hQ#?>kY5Z&@*z)DYl31!%ReVTFuBf=-tDjP|{tIEW%i%X*ok8qT6al%YGVpJ)==1RZFoqB<9%zHzm_8OjSQlxN3_$4V#Um8P9DOfEjVzjA9dr^X-6}*N=dne4N)AD|s?=X!1S(kV0+D2|CVZMK!Lq$VKY{rhsFj&Yxc!t5+BdPdjs3NaL_f8QmJ&S8G>-xMy}<wZ@M@izi{uX2PBvt7)4lpBdV9SrxAEZh0vh6hl6;-RWDkL}h#ypMxabnE%lG$DCdnKk;?Q#MeO*U)jxm6H`ztSr11~ckfhL7EAT-FKcb>swt->X4td_RT_=Cd8+M(I>K!NoXs+0`aVZsxXegyJ!SiLCP#sOx|6ZX)5kJBG$x+Om}d-g0Y#nS3J`4Iy@P^W$Qv{U&;LGNkue?26l%;A{w)FG5b2v0Ha8>WG>%5StzhlDre&`(se;quuEx#H_xP)D7ov;{(3_YG5Qd994nwa=u0WR{h!%@*Rim*7a!GuN)4BvR4}@}FufZ7kRD&{H%&rQ(&xAdxS0tYWYhXBJ72rG7<62-wgRlI*89M-m?tdB%YwjlIL`fq#@KpsU=nbKDw<l;qjR0oU;BHqJd+1WqxQSi}p>%b0z{=`r+GBVkSbYSu0Bo!RvjGSq=J+JQiup(L0q96$A2|>!Acnk$8(z{nQLvRG29w{n;j5ZCyN=syit+Ork4~b23xa_JglIP?iUy?g75iYw&3f=)zo4&xb{M(`<k--xqU*e<F%G5UTYx9#&EzN?)@k$@w8F3}WLJq5?IxA=65zwYf*%(F+@=xbly9+47Ov-Y00f^4aB|qlCG&Stuhyko_$b=KkK$2IPlVepVHRbx*RXoP0_m}cyTDa~mE4jxrZ4}D(KT&2b{nYqMRO2ZD@~&mg<2y27k1#fKr_i4Jw4oaS~MsHaBKwYr<}P2(Z?7qSROL;32YKlu2~pzoF@!XxP+k&<+7}~$+rAfj-k#Hy*hn$`r$WD4;b?1z4I^%CMUoxn8lGMaRQi;b!PdTg}B4aDU762idKLaou;Ytsg8i1D$JPRJSFf$K<k4Qg_%UK1f8g^?lDV8WnYoYQouMWpqEdqe_yXKH?yHN=4)bhCG=XS{LM#SM@Lh0bR6cG;EIkero9yj-UytR_tD29y2&t{l)*YB9LmSl93!*NQbZu81@A_bfpdk)Cm`PHR4Bz1Im<dthx2^#=tPTX4QS$MWj-urk7Ax)oZ@!1&N7Wk+?)5CTO0FR0a+iOwWNey-&te)A<=oM^=b}eQ9UjN7zuXP>`nIax6{8}o?_mkJ1FwJ8u-qjjN&3n>06#gMF>>;QkVGq9?V#3f@(OTZ*$;y{EXo<8vw&xyt{mR`sV!qoxKWQpP#*XMX;Ht1`%kNl0h>+fnLu9{=5?~0^Fe&#S%18o>7|`CTIay7X{4Bz*kUe=#{Uax4iBQmcUMTHGQq3Bt^q}PL>~|NC|Ujfod2u5_w6DI4qO9jIo1dm4gI{`L3ucFzoKIv$1u+L=TzDF6|NdoE3SZRYC%@f$R%{MK+k{dFmniA$xRh<0Kik`5AokN#}VvpzWfs&Z;geXD*QQIExzwpGsC3*pBlug*lY4jUXcJvsh0ww%9RFh}-{T`0ORXAj^wYlqP>r6by92!1JvAmK31Gbx}~>I15wYboySm9>}Ojg}CFWZq88l^PFv50q$^tN)r3aC;g|fa_GbPfcbb5I?9z39zE{&N>xR<AsB*1?Kn`mAp>O&5aagrYS_5B8SKeT<PKLGZ6*g2g2m)UgR#nFvDw`Oq4uho`@7iLYr*I_l|7B6(Sv@oNP2F@BpXjSjRV&>-0^Wnj%1kFTvJ`t^a|_VQtQpWgMWE0jcl<Km0*s4Pcu%RLCu0@twZiN@F8g#-jSoc%%MKHK#>SiHbzn(Jq*FV1SpP`OHA8+KJLzClosrIyG0FpGH~9){Kig{V!m01>YF=)%8=wDP3N2%d4jmi5#ge!*SyUd!K%kZ5T!jC1}YO}(+1YO#kJVgS-(;_>Bz36B1a5ZH*z<;7%hN$YC}@#Bm8b>=;4GPO^iEcVjkQa2j)%l`XOKMW*@@ciJIxR=NI86T>ky+@?XaNLwOsJxC*b{y*ax)y?A+sxQxbf)tp~kon2m>z6oDl(e;U%GZZpmh>|G`U0B0QQ*7dIPR)f*BobV&b+-xsG`S%9rp{@;zHQy%)Upty+q$Iewo%Y-5zTXOu$oL(#nu|@3XJPA!Koy~eHKaR&qT0R%yF#Mj_}MF5@#D*u0YdnCgoep5g<9+M<12#?X-aY?*`jLOts(nr;XVFh4et}bs2c!b=>wsr4L5V;6x7+b$^b(iE1ryOhW`nU;M@vIWb2qFB-kSdgdG{wSWPIWKq-hk<DVfmfoO#0!6$4)Y#G`iwuPf8g1ZhqeDWw{1Ka-dbz@y4$K8f%UwRUk83$O1$i=>mo8{U5D0}qG0KJWKxe933K-w$jewE+A|BC!>6&xES9tF)Gs7~vZQ}#3XNA*>IMEeA02BmAX88gJr5eh!I`KMrB$U@jAgzforE+@;@C;0wk^f@qbQHYQqC1_Q^Aq2)Wl!(Aamc@HbH1^P2L&2<cW6T@iOwP6L3f<!wy6RBCmlSC!K=B?7lwcUIwTmL4;PiYsH_u3D6MRJ3{9%R!g`bp4vd@^*x?0;>F3S?0RU}LqBn~vZ?`?zFDiR-Kr^xkTU0aS5DZ$6%>fupdf)cV^DNyXFU^@2?7POuIDRRkrI5jxd6c3VF++=#&b+YK-zE-EPK$!(>7U=_Ej;*9Jj!!GoIS+38>BX~M>Zi0Vb(d>V-CqUmBZ+3gejkV?Y2_Q(c<+T_uqu+btl_!F_37R9T23Qy!$LyAS8|n;gKoDAlO#`^V|G^;+EV?Y&)REiJd6qIjA!PHBiVBTwyILLx$r}sVRPebsCHgBp5k-x~a(f0<#!88zqu55-kpEwL}H-xv_H5AQ-es(zDbB#um_Dl<L~#ty3KZA$u>Ql)Xya$wMS`z${I0i{FWJ3{VdF%vn(-OVAIc!EMSkG0!59`$H(1X3@|Yi{W_UwGx<&v?qeqKQyopi7N;+AFKLyMt>?$PN8tIn8_J10{C62!f_Bomsu)6<ESLfcVMW{u#7{?nli4F&7sdy$)7v)K<fxypKY`=BiU%Grl;79II=mv^#V=XgYV$I0Us&&EYC${gI4x0pVW931M(G^LOp?LcFTk56r8;V*B$U!Cvb)5z*DKB4?>-0v?8YLYxSVh3`HGU8CWD{gCo?)xWUl~p4v<^BC>~<^lZx`3e7V+2$g|0zh*K-(OmM|Pi0;Ujy#h#HF-VL_OS8NuH%jaMC-7NsD-DAkhDY%e3Wh437S~rFum?(u8wf7G>9iBrwp`f-t<2_p#C=WZ5kKYb$nAsA-pG{uj`cDiePj^y^_pDrdcQO-z2~*-9_Y?xSLA|yc*`(zEK#F8H0$%RbLGbxCN$S-y#vFo7A*>z>~dyV3D~K*fAc_xkpKL_=tm%`3MPlY5}&RK_=qX4NBHSkVm8L#7Mw<Hp;CqlF3;19YmL49~|_cdt?EXbB^nfiP>BN0Hb|`0CraIq;1d=G?fZ92@I3A`T5hpvk<T&T*jd68-9<O1rlt8+&e}jZPrlE3Ve(XE#~f}f)PbCFfgwAj$*QdXE~q=x*4#ViyGA4v<qq+n4r`?#SBN+Ub?|(>i4W@;F=BU+ms92NHxE6Y4mMfM^mjPIxvXb&sh@fKKm8{*^|_j9GHZ8x=@sp+ct_~2T$dI&>2zes`h$7N&S%^oAXnAO=VBpCM`XW{4SMjzopfQl(_vjb}UQc$v^aXCCPr0W=$)yCq-s!^vZYcc{*5=$2KrC7}#^PwH;3bTWGwYm1WM5bl^=Uet3v`q=Ocw;J7dQO)eYLZUpk=TaYjf5t_Xa&Az<09BRg)qm8s%@ib;;%=CL~JV{bK&|Zl)S-K{Gt<X&+*+E}DWa9{aLL=vZZ)*laD|I~ih7m}6t_i+{WLb$tho-KLmF$SmZO`4ea6n&_c@wC<kkE@+UrgwEpHK&!ct?@yOAI=R79X-`?c`bdNIMjm0Cg|G!2umraPgJOslc%=Z~}v#N80gh<kA`YD3-T`+Z605l|asHQO*uor<(B@jL5X&Guz}*ly(%I0CXZw@;dF9(l>Lg-x7qO1<kNuIHTvI5VEa`KV*5P4m=Mm_xpVzmT7W#U&*MBL;%e;3_|m{9{9dmV<n9m3^tqzOueb{nh!P;<_%1%HVxN$+2DU_0vhy#=14t0sL5m4bu3CyCM#9k;2Hh~_-*H&p5on_UKi$cEa=3YdhAdlv)%Smo5nxUVrn0&MEq3fzQIxVdK%TPr%&*DQ&R>iGiC66d7zEOe-t^n0WO8ZRw(lLz^+YX1SNy1U0TQ6kc#u?fWQw<oWZ8ln8C)-$bgP%U|$T!EqEWX+05gtlBc>ys1C{jA10vjdX1_8?K^n3P>unOw`Oz~{)tiSY%!3<2=IK@SD&iDWz~$LOk2KH=WFX^>xaMW)@89fPqJN+JveKiZ=UU`1emL65taAw3|O%dZ`v9~(tuv$lU89lGlxjlq*^9l&@iK&w3p2RmNH*fpK(K!4&&hp=2~-fF08~=q9v>j$;s^!T>Cd!mUAYN1594z4_J&w0Ki4yT;!FNJ7gvm-9_b!l8Z2HDaKu?Oq3YDyT~0%0*a$FEq%$v@<%2rJYC~+szwPciN}Kx$~=lc-ci`e5nn`HtKDfce<%!>HBtbUi%K5?<hjfZ<&Ji$?pY~7eRc18Qj&~>iknOxe&nPf&`+q}KtU(VN43=fnhr&<QC3av?+q4$%ogM$mz)UjiP%|HsW~;!wWu)Gi%pKOA_N}E3Z_T837P|V_(g)j(^|nXmeSdu=r;1iBsG{KkTC)|+?N&KK<{d1g1M+7M`WVFY%v7vI~og=TuFxYDVQ(m0OI^n9aP%obXAy@v)8ZBUTzwzvAxM81GIL6JwRy~;9<8RcrjS|0_!d*T0#@J3B%f<x){S?a*V?mo0-U(+SC~7v_k`hj!2ZrRG$d5=-Q9Y=$Jb05jqFG=%CjK4aeBz05KjPZ$@W)MCcq~<2{_7$zFqwHHZE9;Nibvu)p^dc_#D-CJ#PhJb8jVM9T>`-Y33l@M-vE196UsIO8Xf866pOh1HzKdruH&M2%_giGlZz37M~*R4kbX<2l2h_**M2OQvI~^sEOn-%1^T<&7+vt#eIKe8>E_ZD|8KEdOMCb5(3YktNkDfzF61hE4UnM$XfrZeQliL^$STg<^FHi_%QSH21^>&@P34^@vV?(+PjR0n?Mhzj}-b)KpEtIx5E1(5Bn27!L&pc#gN-bUaM?$I-T1kB2q<!1&j;F+$8aXvnH7TCfnHv@w;rE`QKz=cfor#KH}ZCS6d1<E=TPUP!JEUaC9Y<L6!TxXwOi`RB|`2_jEH0~<7{>u59(!gL;RkJ@C9w0r->qph|H*_U7N;oR`aXHyfT5}q%`42@>y!4MEB+B)*-a*K7QN2^W;OVd>>mx7AdNcpO7U-KwhwIn#`!z+hDUnjRPn+%4(6L#>mbIg2CAC-iO2Vk<(o_%(gHl-vMGx@2HEvSka{OlQj$l4P#u0YW>y9_?#(_eUj?9;vq2s3+8>%tb;sqd5u+Ao6q|Jgt@LnsZW!N!zHSuH}&^QRLUw>rxW=3}X@$fO18)y`SqQWJ4n61NW|%t5za2sClAG7wgb83j$L1yum1r$SJ_{i=a{6Aa5omW7enO}3YIf$4}==>lCg$xKtEQ9_54Zqh}7VFcNQaxa2s9bDB~ts`R6RzgR+Mv%m*H($jlOC(9spKoJT(SnsUUqlX2lpVcK#sUN-FqDl0^aQ@Rk>^<?<yshh6t#q<DyO0t-P9+zH{2@DL5MIDcEkZje_DI8n_A8sBV^05*Uk`48KVJy>Vw5mQnx)6P%Ci9+szv7VbzkNns1;k=#vJF<#4W9ZxC@dtB~8<Z>v>i)LvluXcRX#=KfkAUB6D8AMLa3ZTsMR%eQr8ZHBQ4O%b*SL_-lu6P+B6$7pfNVoK@;RfVAQ$okUwaMYtuWj|OKV^nF}1%B;6sl3)X2JjvPpG1_xPG{iiB>JaGp0cEaCL62naCtG(lvppqF6FkViW~1WO6cEO%1s|pYS(V#;!dQ`o7M`rUHXlhGN9|h2F*0M)r(&qYeFSzS58wir^rZ@3%S-&FF|+qRKx|_a5>dK2aF{84%fFBUZwWx7oA)SrR`2v_!w@8=`yqv16RMcivywNXcN|NA*5>4^wp~C&Z#7VJ%eTAA!^T{8I3BRL-p9&Nvvv+7SY-wz1_<qhV<84O*+&;Ezs4j8}ve_yc_Y;Q%qv!*V@@hJS1ON+M@byn~J+BhPdWlw<;j{1eZU}x)emj6gGXDk1~GhmHXiBqBwk@vdFUdibK^`6cV}uORLUHW`y{#<_1neMUk(eMrEkop&=o&I||0;Bn@yK3{+8~0ZRt8t_DW2xq&)OXx^mdW<rzP7BXqVITj|slTe!b)H86~i^bo-SQ>P}gr^>A9=RWIsYa_^Q?R1pWPNDAyw<DWb|^2%X17T6en1v;KMl-i+5w2!$`}I-ImidFD2o&Y2dQ(8rcroS8_>9AV@(oQ$_X*f$Khw}Fv9H+eY!Ag9NJLD5cR_hP!y8{w@Fs3hUfkw?xTkU7OEK|1vgn>VyX~UAQO2A<s@SGSF%3InO1>HmHs@8FhWWJN;QtJ?Zf6R1B@bw#lLm(oV(iRw+F)^akhDWTvZQI+W+b9#HPLd!AN+fD@QK7J<*o1PmMEx?$Pni9)PxE_*^wDSNckLs_*dNjnxE1hEo(qWt=24$%JN*{hPK(nzOrTza?1>3(`EgdnuyDkhUDbUn}taCY0!qQSviI%jvx>F!N1tx{At=sz?fQkP*TTtbnvM8I3or#A%K@=uLE4Pzq%eS{8h&1ONYn>X7$^s8{BDTE6LJF6AeXL}E|>rZ*2X#e!(d#O1<PAs&9EiZ!SyK6C9FNzRN;fYVzZ@ITjMpYAgzuQv6?;etNd#>N&WuhLWKwF388u?kevOpQ3e5#SdPzpJ$i5E>c;(9jD&h;wAX?Pr+$qv8?D5Sj~k%o4LE<WS_`NW81jv6R9?GnkylSNmYghAhcs=Q_h&f)v~vc_Asw8tz`}BERz3(9M>7G;qT*xl@6=%C3w6G*|CIF{XhFV>G|JwcM#kUIrq2NQykWzS(+z`R>=t)3>iquTHT(m$M5PT*!CoyhTp^2f;HB)i7puEiIRxx68H5;I1nD^iB1(8ltH|F%T@vLJFTo)0Cw&q66FwraO%0K;OEevxbGb-c;mLW8%HD-^ZOda6J7g7l~e)$D}~4N(jx=X<jnPWlx<v9-3D7n+V8vzng%vv?XOUFo<h<eGF9(>QvjLLY<$%#pbijx&xQ7T7Vgp$M-hH4XUF=3G^Xr0M}Qbzqd{qWe_+9oxFCyh5RIgl)Nmt$j|Tq13-vAeC!`Q+Z9@dvOW--IEd<oUgnDDE=)~2cR^pMC`GcsqC`~2xz14H^AFlP*T2?LU1AX&k5}Ez7M)HtnZh9E6GQH!s%p&w1R5#hosa-$WHWK~P-HN?e>mQEKGh~%Kf_3&z$NtP<V?ziEW(7y1S?ju{l+F(lv_!K&h6WO4`(jJf@QAEJgP6TSXYkwH}Ob(>l-}mJMTWoFIQmx&{q#%OGdT2PBySs4+70xQ-waXrCfsH1<FF{l`vAbfMUF}8LBQ4+*X!yYS+<gpTC2xikq#h*jcQQI&!@rDnsb(;?B*@*3b0bsUkN))A?^{in!7=0B0u4Ks370)yId+LuE484^1v4%VOT5$zmSxhCJ3Tet&uT>)TW3Q;l!fK&xu@?xMp%R*zrKem(Ct;Yu@B!w+X~&R$-TfCbk96E9@J27mA$V2?hc&<&I-A9&8|%Xe=vgNf{`fBbfKc}Bka&riMSjsLjDJLn$PC6z3JUY-{$MFnnQW*s_J!Dqt=!uT3aKUTmQfd-aJ8^d#0yo|2)q;+i&v8#k%<D$maAr_k@zJrX&=Qd2jW!+L-l9c4Vx-U;ZoFRQKn6!+zi1T8Bgas<s;0wwyLck6kR*72YFdQIrTLkhGF5X=^=NFDU$m%rR*y{A+l|7%$bCK2Sa^TGdI=j=kLL|q|*~Ke*O;sPn-XT2&UCKxcIJ3?|#6<40{iMxoz~Vs_j%-_(Jnw$Xm{gNzn3HlIyF4aue5Yh=Acy>D%|PEP7k%YM1e?X=W=vS*p-6gGLTVuSM^@aHR@IR04Q;wjo}TpFLYQ3B)%!&rJVaH&dAsD0ppd{|PWx4!#>@Whqhi68?bR#D+As2yFXq(0`2(&{1^#dJ;x_ndWj$XPc`Qn!$z$1a<-W<^?DY_DGCC^x`{^63H!&LBWN*&jo~yTP8ZYLQp*lsDp$bdv()&5hLcMm4UY?)tEz_&uMHQaMp+3H2)#BkwY6PrRM~#Z8NnRpdhh@!jm{&9u&^YROBr<bZ0ah!6n{_-x)%4*Oog!mSyV9DO;)*?jWm=c_roaH7ZCO5Mv8x&+smO9&?JX~xI&63jnkd>(g>!Al#ZctXP8`j^2Jg+xuVBkdl|R01${#;nnwWcrx@>a$)t}nK!W#MNDY!mZ8g%2=fQ?)}fqY@7!oK_V&;P}1JXHa4)Lv!1(wM7VclOSkeK-l2O5K%iyllU;36qUzrTFRuGC5In3>llls26}azgFuO95cQqEAdFzTrEATG88yf`A15-r-eq;;DA~45{`3Kz?{lh=5%11-mgS4N2e*^3}Ox6ov2^EG$hu+^pkag$)-X<lqVjVu4uPJ3zV4Z&4ktG+^N^huuhrG>6j=d<f?<&>qjbbwxyCO>umk#gSh%D{0nHUf~hZx${pd=00#9Ctn;-y_PoE^nwA`x^&{pehuG0=wfFG`a>%TS`gzT=M<G8mWGCf1H}J0!8XHOKMFYcg_M3+P<WG<cQ+XxEPZ$WUW?por5veZHdNbZ4P4Cm(#(5(ksy=7CIhSL#ww2@0iy6;)9IYv(m8(j&Z1OP{>L-Ra>u+`iE)oNbo&{Ih)RL8LJ0JusNw?u{U8B<?9Xizad9+H9YD|`0@QDlgb(!;*xO|XTGW2(!v9+HZ-E{NV=3vAQ$HRl+7-op;@RI4pV>Dj_K`+#{<Rs=_;gJJNLkD;ji-)iHCB!N$Bz=Lf2_Dm{dkx{*#FRDf$-;-7XYh4?3O>)p|GWk(nk}$IkS#-Q?DB^_dcGFOsI6I2uFj;eK&e0_MPfX=KGP9fJf(-zJ+mg?*S5~AC3}2nB+Vox6%n8GAT@dJYD^PXE~>$|nDNQ4U_gIA1%oZ+I5VkX>ShRZ2GjBxo%6SE&t9FMUY%JEk+KFsHt?x^iy%Y|MT2J4YLqr9{~Z8I7cWr}n@U<MUMlWkFS$lx;mdCma_qI%qNbsIb%inxD4U=wL-bu)tGBN@@3+kyn$F)nZ&qxeFD`)g&V7+*d0oz4|NYGyYv#IPfelk^HGFw_2KSw-(_h}4Ip?n(^gPf0dH&(*1HUSm>i3hH{q^k9d4GBS_Vn^!&fm`drKW7*VB!Mxy8x6t>ruSlL6dIUZt4X;np|{2+E|uh!#6e+A8yqgQ}6VqGPLsTIkE`FXM7`ek4-Ut-tMXLJfxcY?YE;NRD8#EA6T`mW#MwtADh0}dVPLz`o<i2tB^CbPHBfjTTS>BnW;_bovzE_>mDnqWhV7RBl{vnWA@|uh0z=UqIWi61jr$_utPfiZnbHFU7KaTQHxWx=)O1L==}gGqYV+TF%ouu@!{+e!zNenB+@Y8zn^_@fA)X&8k`+tkCh+O^*%Q3BHV0Y-pcQ1=2Xd2+~ha(j8+vRzqRW?Q<XJ0@eL#6K_#~Ft9bgRga)9NoiRJ_E?>do{N-N`6W2Vd2M)P<VOgTyD-^2o|F@kNMq*})>|!9ybOJ%hrN{NFUogBt;W?C#oT=wGZ|^Vz$kL^m^|=M+KH9w~_!V=EkFInsUlCGTJ2yW#ukjtT4!_fgZFD}o7SIvax^({Q!@CPEdP%+@nyP_wj&CZ93p_EF$8lYhCdj#{KI5|`P!u2Q8Z33TXXqjLnly4U<h4TF;fWu7uZhApu*5CHaxFDW<~_YRK!&AH<e@R8v)~HbbEu$}NEh(F8ZmRi3%&1FztyNIc!IR``JIb27jQ{^_4RgJh?9Gwzx(?7JX%N?L*s7m1Jg*p=mk1RuEN89RL)rPC2a={$G&P!JKJ)v?F6^6`ys2SrXt&HrlqKS0hQz=u7X6*n$7s_kd!m32E5@7D(KfIxD~QYVtfYA>c(MGViZ#YS|j)4IInrAwA|b8W#Ec*6q?am5Zr~k0{sP6gudjG*0E-mMTXjFzd4Yh$~V|)5Z_j--P}hH*_02>tr32ELEjEM+jlcZd70PaliRLpZuZ%DrLwOh^`rN^GM4+LXx-aeYqsfb2WZdegX-Frc<sbo?{9K^=>U$DlAI`0h0?D16;>q%yC^jPlYMAwf=&SQ`{Pj>U{w%vy|-r-*?LHET0O6@=y5ah#7G43<=buWDg}1G#7$WDtJgAgZ?dhg{{!@QsQ~'
HASHES = {'research.py': '43d68cc0c5b1edc5fb6bf9dc505ae9ba5f5178f76fe8c388918a0e6ebe300c84', 'neuropelvic.py': '11af35930b67c1f9d52621e1c00319bcd8c3087f68e1f4044026adfbfc485c11', 'valuation.py': '95dcafec504947a956a2b86f8e7d8ac222bc7a2fc33b315c12104b6ee05fedbe', 'continuity.py': 'a83ab952be9868539d0e98fe1bbe0d872f7bcbf9f60d50cc799fee1794c44ffe', 'evening_run.py': '8294e4c79eece382438d7228104da9b62375e11e9a72d92a38b370f406c532db'}
SCHEMA = "tadash-research-20261108/1"
DEADLINE = 1794159000
PREFIX = "NasurayaResearch20261108"
WORKER = "runtime-e747ee5d4aaa642c"
MANIFEST_SHA = "e8558cf14cb7ed1f6273a7dcfe75ba287d7a44ec39b3a2feb730d816072f909b"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def emit(path, data):
    tmp=path.with_suffix(".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def emit_json(path, data):
    emit(path, json.dumps(data,sort_keys=True,allow_nan=False).encode())


def quote(text):
    return "'" + str(text).replace("'", "''") + "'"


def ps(command):
    result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
                             "$ErrorActionPreference='Stop';" + command],
                            capture_output=True, timeout=22)
    if result.returncode:
        text = result.stderr.decode("utf-8","replace")
        err = re.search(r"FullyQualifiedErrorId\s*:\s*([A-Za-z0-9_.,]+)", text)
        raise RuntimeError(("ps_" + err.group(1).split(",")[0][:35]) if err else "ps_error")
    return result.stdout.decode("utf-8","replace").strip()


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        return None


def reference(runtime):
    manifest = (runtime/"FILES_SHA256.json").read_bytes()
    ca = runtime/"cacert.pem"
    if sha(manifest)!=MANIFEST_SHA or sha(ca.read_bytes())!=json.loads(manifest)["cacert.pem"]:
        raise ValueError("clock_ca_pin")
    op=build_opener(ProxyHandler({}),NoRedirect(),HTTPSHandler(context=ssl.create_default_context(cafile=str(ca))))
    url=("https://api.github.com/repos/zurvanproject/zohraya/commits/"
         "64a7f40d57c06705ef8e692c4048f5b6c5cf36a1?evening="+uuid.uuid4().hex)
    begin=time.time()
    req=Request(url,method="HEAD",headers={"User-Agent":"NasurayaEveningResearch/1","Cache-Control":"no-cache"})
    with op.open(req,timeout=8) as response:
        server=parsedate_to_datetime(response.headers["Date"]).timestamp()
        if float(response.headers.get("Age","0"))>10:
            raise ValueError("stale_clock")
    end=time.time()
    if not 1794096000<=server<DEADLINE-90 or end-begin>10:
        raise ValueError("outside_window")
    return (begin+end)/2-server


def register(root, cfg):
    exe=quote(sys.executable)
    routine=root/"evening_run.py"
    deadline=cfg["deadline"]
    start=cfg["started"]+603
    parts=["$created=@();$ep=[DateTime]::SpecifyKind([DateTime]'1970-01-01',[DateTimeKind]::Utc);",
           "$who=New-ScheduledTaskPrincipal -UserId SYSTEM -LogonType ServiceAccount -RunLevel Highest;",
           "$settings=New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 4) "
           "-MultipleInstances IgnoreNew -StartWhenAvailable;try{"]
    for mode in ("sample","final"):
        name=quote(PREFIX+mode.capitalize())
        args=quote('-I -X utf8 "'+str(routine)+'" '+mode)
        begin=start if mode=="sample" else deadline+2
        trigger = "$at=$ep.AddSeconds("+str(begin)+").ToLocalTime();$t=New-ScheduledTaskTrigger -Once -At $at"
        if mode=="sample" and deadline>start:
            trigger+=" -RepetitionInterval (New-TimeSpan -Minutes 10) -RepetitionDuration (New-TimeSpan -Seconds "+str(max(1,deadline-start))+")"
        # An installation shortly before the deadline gets only the explicit
        # initial sample and finalizer; the later trigger still enforces cutoff.
        parts.extend(["$old=Get-ScheduledTask -TaskName "+name+" -ErrorAction SilentlyContinue;",
          "if(-not $old){"+trigger+";$a=New-ScheduledTaskAction -Execute "+exe+" -Argument "+args+
          " -WorkingDirectory "+quote(root)+";Register-ScheduledTask -TaskName "+name+
          " -Action $a -Trigger $t -Principal $who -Settings $settings "
          "-Description 'Finite Tadash research to 21:00 Tehran, 2026-11-08'|Out-Null;$created+="+name+"};",
          "$k=Get-ScheduledTask -TaskName "+name+";if($k.Principal.UserId -notin @('SYSTEM','S-1-5-18') "
          "-or $k.Actions[0].Execute -ne "+exe+" -or $k.Actions[0].Arguments -ne "+args+
          " -or -not $k.Settings.Enabled){throw 'TaskMismatch'};",
          "$x=[xml](Export-ScheduledTask -TaskName "+name+");"
          "$b=$x.SelectSingleNode(\"//*[local-name()='TimeTrigger']/*[local-name()='StartBoundary']\");"
          "if(($null -eq $b) -or [Math]::Abs((([DateTimeOffset]::Parse($b.InnerText)).UtcDateTime-$ep).TotalSeconds-"+
          str(begin)+") -gt 1){throw 'TaskBoundary'};"])
        if mode=="sample" and deadline>start:
            parts.append("$n=$x.SelectSingleNode(\"//*[local-name()='Repetition']/*[local-name()='Interval']\");"
                         "if(($null -eq $n) -or [Xml.XmlConvert]::ToTimeSpan($n.InnerText).TotalSeconds -ne 600)"
                         "{throw 'TaskInterval'};")
    parts.extend(["Start-ScheduledTask -TaskName "+quote(PREFIX+"Sample")+";",
                  "}catch{foreach($n in $created){Unregister-ScheduledTask -TaskName $n -Confirm:$false "
                  "-ErrorAction SilentlyContinue};throw};'VERIFIED'"])
    if ps("".join(parts))!="VERIFIED":
        raise RuntimeError("schedule_verification")


def main():
    if os.name!="nt" or sys.version_info < (3,12):
        raise ValueError("host_requirement")
    worker=Path(os.environ["PROGRAMDATA"])/"NasurayaModelWorker"
    if worker.is_symlink() or worker.is_junction() or read(worker/"owner.json")!={"schema":"nasuraya-model-worker/1"}:
        raise ValueError("worker_owner")
    root=worker/"research-20261108"
    owner=root/"owner.json"
    if root.exists() and (root.is_symlink() or root.is_junction() or not owner.is_file() or read(owner)!={"schema":SCHEMA}):
        raise ValueError("session_owner")
    root.mkdir(exist_ok=True)
    # The protected worker tree grants access to SYSTEM and administrators.
    acl=ps("$bad=@();foreach($p in @("+quote(worker)+","+quote(root)+")){"
           "$rules=(Get-Acl -LiteralPath $p).GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier]);"
           "foreach($r in $rules){if($r.AccessControlType -eq 'Allow' -and "
           "$r.IdentityReference.Value -notin @('S-1-5-18','S-1-5-32-544')){$bad+='acl'}}};$bad")
    if acl:
        raise ValueError("private_acl_required")
    if not owner.exists():
        emit_json(owner,{"schema":SCHEMA})
    data=json.loads(zlib.decompress(base64.b85decode(PACK)))
    if set(data)!=set(HASHES):
        raise ValueError("package_manifest")
    for name, code in data.items():
        raw=code.encode("utf-8")
        path=root/name
        if sha(raw)!=HASHES[name] or (path.exists() and (path.is_symlink() or path.read_bytes()!=raw)):
            raise ValueError("source_conflict")
        if not path.exists():
            emit(path,raw)
    config=root/"config.json"
    if config.exists():
        cfg=read(config)
        if cfg["schema"]!=SCHEMA or cfg["hashes"]!=HASHES or cfg["reference_deadline"]!=DEADLINE:
            raise ValueError("config_conflict")
        if time.time()>=cfg["deadline"]:
            return "EVENING=WINDOW_CLOSED;END=2100TEHRAN"
    else:
        offset=reference(worker/WORKER)
        cfg={"schema":SCHEMA,"started":int(time.time()),"deadline":int(round(DEADLINE+offset)),
             "reference_deadline":DEADLINE,"offset":offset,"hashes":HASHES}
        emit_json(config,cfg)
    register(root,cfg)
    until=time.monotonic()+12
    while time.monotonic()<until:
        if (root/"progress.json").is_file():
            r=read(root/"progress.json")
            return ("EVENING=INSTALLED;SYSTEM=1;S="+str(r["slots"])+";PLAN="+str(r["expected"])+
                    ";HEALTH="+str(r["health_ok"])+";EVERY=10MIN;END=2100TEHRAN;API=0")
        time.sleep(.5)
    return "EVENING=SCHEDULED;TASKS=2;SYSTEM=1;FIRST=PENDING;END=2100TEHRAN"


if __name__=="__main__":
    try:
        summary=main()
    except Exception as exc:
        msg=str(exc)
        detail=msg if isinstance(exc,(ValueError,RuntimeError)) and re.fullmatch(r"[A-Za-z0-9_]{1,60}",msg) else type(exc).__name__
        summary="EVENING=INSTALL_FAILED;ERROR="+detail
    print(json.dumps({"status":"ok","summary":summary},separators=(",",":")))
