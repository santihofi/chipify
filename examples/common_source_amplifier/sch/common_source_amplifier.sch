v {xschem version=3.4.8RC file_version=1.3}
G {}
K {}
V {}
S {}
F {}
E {}
N 90 -80 90 -0 {lab=vss}
N 90 -160 90 -140 {lab=outp}
N 30 -110 50 -110 {lab=vbias}
N 90 -290 90 -250 {lab=vdd}
N 310 -80 310 -0 {lab=vss}
N 310 -160 310 -140 {lab=outn}
N 220 -110 270 -110 {lab=vbias}
N 310 -290 310 -250 {lab=vdd}
N 220 -110 220 -50 {lab=vbias}
N 30 -50 220 -50 {lab=vbias}
N 30 -110 30 -50 {lab=vbias}
N 0 -110 30 -110 {lab=vbias}
N 90 -290 310 -290 {lab=vdd}
N -0 -290 90 -290 {lab=vdd}
N -0 -0 90 0 {lab=vss}
N 310 -160 320 -160 {lab=outn}
N 90 -160 100 -160 {lab=outp}
N 250 -220 270 -220 {lab=inn}
N -0 -220 50 -220 {lab=inp}
N 90 -190 90 -160 {lab=outp}
N 310 -190 310 -160 {lab=outn}
N 150 -0 310 0 {lab=vss}
N 310 -110 370 -110 {lab=vss}
N 310 -220 370 -220 {lab=vss}
N 90 -220 150 -220 {lab=vss}
N 90 -110 150 -110 {lab=vss}
N 150 -110 150 -0 {lab=vss}
N 90 -0 150 -0 {lab=vss}
N 150 -220 150 -110 {lab=vss}
N 370 -110 370 -0 {lab=vss}
N 310 0 370 -0 {lab=vss}
N 370 -220 370 -110 {lab=vss}
C {sg13g2_pr/sg13_lv_nmos.sym} 70 -110 0 0 {name=M1
l=2u
w=100u
ng=20
m=1
model=sg13_lv_nmos
spiceprefix=X
}
C {sg13g2_pr/sg13_lv_nmos.sym} 70 -220 0 0 {name=M2
l=0.13u
w=200u
ng=20
m=1
model=sg13_lv_nmos
spiceprefix=X
}
C {sg13g2_pr/sg13_lv_nmos.sym} 290 -110 0 0 {name=M3
l=2u
w=100u
ng=20
m=1
model=sg13_lv_nmos
spiceprefix=X
}
C {sg13g2_pr/sg13_lv_nmos.sym} 290 -220 0 0 {name=M4
l=0.13u
w=200u
ng=20
m=1
model=sg13_lv_nmos
spiceprefix=X
}
C {ipin.sym} 0 -110 0 0 {name=p5 lab=vbias}
C {iopin.sym} 0 -290 2 0 {name=p1 lab=vdd}
C {opin.sym} 100 -160 0 0 {name=p23 lab=outp}
C {iopin.sym} 0 0 2 0 {name=p2 lab=vss}
C {opin.sym} 320 -160 0 0 {name=p3 lab=outn}
C {ipin.sym} 0 -220 0 0 {name=p4 lab=inp}
C {ipin.sym} 250 -220 0 0 {name=p6 lab=inn}
