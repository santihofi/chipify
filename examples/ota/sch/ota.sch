v {xschem version=3.4.8RC file_version=1.3}
G {}
K {}
V {}
S {}
F {}
E {}
T {ibias1 nominal
current: 8.5uA} -300 -60 0 0 0.3 0.3 {}
T {n bulk
contact} 470 -210 0 0 0.3 0.3 {}
T {dummy for
diff_pair} 350 120 0 0 0.3 0.3 {}
T {p bulk
contact} 570 -10 0 0 0.3 0.3 {}
N 40 30 40 80 {lab=#net1}
N 170 80 300 80 {lab=#net1}
N 300 30 300 80 {lab=#net1}
N 170 80 170 110 {lab=#net1}
N 40 80 170 80 {lab=#net1}
N 170 170 170 240 {lab=vss}
N -130 170 -130 240 {lab=vss}
N -130 100 -130 110 {lab=ibias1}
N -130 100 -80 100 {lab=ibias1}
N -80 100 -80 140 {lab=ibias1}
N -90 140 -80 140 {lab=ibias1}
N 110 -300 110 -250 {lab=#net2}
N 40 -250 110 -250 {lab=#net2}
N 40 -270 40 -250 {lab=#net2}
N 80 -300 110 -300 {lab=#net2}
N 110 -300 260 -300 {lab=#net2}
N -80 140 130 140 {lab=ibias1}
N 40 -250 40 -30 {lab=#net2}
N 300 -300 340 -300 {lab=ntap}
N 0 -300 40 -300 {lab=ntap}
N 40 -0 90 -0 {lab=ptap}
N 250 -0 300 -0 {lab=ptap}
N -170 140 -130 140 {lab=ptap}
N 170 140 210 140 {lab=ptap}
N 490 -290 490 -270 {lab=ntap}
N 490 -400 490 -350 {lab=vdd}
N 600 90 600 130 {lab=ptap}
N 600 190 600 240 {lab=vss}
N 400 40 400 50 {lab=#net1}
N 400 110 400 120 {lab=#net1}
N 340 80 360 80 {lab=#net1}
N 340 40 340 80 {lab=#net1}
N 340 40 400 40 {lab=#net1}
N 340 120 400 120 {lab=#net1}
N 340 80 340 120 {lab=#net1}
N 400 80 450 80 {lab=ptap}
N 300 80 340 80 {lab=#net1}
N -130 240 170 240 {lab=vss}
N -170 240 -130 240 {lab=vss}
N 300 -400 300 -330 {lab=vdd}
N 40 -400 300 -400 {lab=vdd}
N -170 -400 40 -400 {lab=vdd}
N 300 -150 340 -150 {lab=out}
N 300 -190 300 -150 {lab=out}
N 300 -150 300 -30 {lab=out}
N 170 240 600 240 {lab=vss}
N -130 20 -130 100 {lab=ibias1}
N 40 -400 40 -330 {lab=vdd}
N 750 110 750 120 {lab=vss}
N 710 150 750 150 {lab=ptap}
N 750 110 800 110 {lab=vss}
N 750 180 750 240 {lab=vss}
N 600 240 750 240 {lab=vss}
N 790 150 800 150 {lab=vss}
N 800 150 800 240 {lab=vss}
N 750 240 800 240 {lab=vss}
N 800 110 800 150 {lab=vss}
N 150 -190 190 -190 {lab=ntap}
N 300 -400 490 -400 {lab=vdd}
N 230 -190 250 -190 {lab=out}
N 190 -160 190 -150 {lab=out}
N 190 -150 250 -150 {lab=out}
N 190 -230 190 -220 {lab=out}
N 190 -230 250 -230 {lab=out}
N 250 -190 250 -150 {lab=out}
N 250 -230 250 -190 {lab=out}
N 250 -190 300 -190 {lab=out}
N 300 -270 300 -190 {lab=out}
C {sg13g2_pr/sg13_lv_nmos.sym} 20 0 0 0 {name=M1
l=1u
w=4u
ng=4
m=1
model=sg13_lv_nmos
spiceprefix=X
}
C {sg13g2_pr/sg13_lv_nmos.sym} 320 0 0 1 {name=M2
l=1u
w=4u
ng=4
m=1
model=sg13_lv_nmos
spiceprefix=X
}
C {sg13g2_pr/sg13_lv_nmos.sym} 150 140 0 0 {name=M3
l=2u
w=8u
ng=4
m=1
model=sg13_lv_nmos
spiceprefix=X
}
C {sg13g2_pr/sg13_lv_nmos.sym} -110 140 0 1 {name=M4
l=2u
w=8u
ng=4
m=1
model=sg13_lv_nmos
spiceprefix=X
}
C {sg13g2_pr/sg13_lv_pmos.sym} 60 -300 0 1 {name=M5
l=1u
w=2u
ng=1
m=1
model=sg13_lv_pmos
spiceprefix=X
}
C {sg13g2_pr/sg13_lv_pmos.sym} 280 -300 0 0 {name=M6
l=1u
w=2u
ng=1
m=1
model=sg13_lv_pmos
spiceprefix=X
}
C {ipin.sym} 340 0 2 0 {name=p3 lab=inn}
C {iopin.sym} -170 -400 0 1 {name=p4 lab=vdd}
C {iopin.sym} -170 240 0 1 {name=p6 lab=vss}
C {ipin.sym} 0 0 2 1 {name=p2 lab=inp}
C {lab_pin.sym} 340 -300 2 0 {name=p15 sig_type=std_logic lab=ntap}
C {lab_pin.sym} 0 -300 0 0 {name=p7 sig_type=std_logic lab=ntap}
C {lab_pin.sym} 250 0 2 1 {name=p12 sig_type=std_logic lab=ptap}
C {lab_pin.sym} 90 0 2 0 {name=p13 sig_type=std_logic lab=ptap}
C {lab_pin.sym} 210 140 2 0 {name=p14 sig_type=std_logic lab=ptap}
C {lab_pin.sym} -170 140 2 1 {name=p16 sig_type=std_logic lab=ptap}
C {ipin.sym} -130 20 1 0 {name=p1 lab=ibias1}
C {sg13g2_pr/ntap1.sym} 490 -320 0 0 {name=R2
model=ntap1
spiceprefix=X
w=0.78e-6
l=0.78e-6
}
C {sg13g2_pr/sg13_lv_nmos.sym} 380 80 0 0 {name=M10
l=0.13u
w=2u
ng=2
m=1
model=sg13_lv_nmos
spiceprefix=X
}
C {lab_pin.sym} 450 80 2 0 {name=p17 sig_type=std_logic lab=ptap}
C {title.sym} -220 290 0 0 {name=l1 author="Santiago Hofwimmer | JKU IICQC"}
C {sg13g2_pr/ptap1.sym} 600 160 2 0 {name=R7
model=ptap1
spiceprefix=X
w=0.78e-6
l=0.78e-6
}
C {iopin.sym} 490 -270 3 1 {name=p18 lab=ntap}
C {iopin.sym} 600 90 1 1 {name=p19 lab=ptap}
C {lab_pin.sym} 600 130 2 1 {name=p20 sig_type=std_logic lab=ptap}
C {lab_pin.sym} 490 -290 0 0 {name=p21 sig_type=std_logic lab=ntap}
C {sg13g2_pr/annotate_fet_params.sym} 30 100 0 0 {name=annot1 ref=M2}
C {opin.sym} 340 -150 0 0 {name=p5 lab=out}
C {sg13g2_pr/sg13_lv_nmos.sym} 770 150 0 1 {name=M51
l=0.13u
w=4u
ng=2
m=1
model=sg13_lv_nmos
spiceprefix=X
}
C {lab_pin.sym} 710 150 2 1 {name=p8 sig_type=std_logic lab=ptap}
C {sg13g2_pr/sg13_lv_pmos.sym} 210 -190 0 1 {name=M61
l=0.13u
w=2u
ng=2
m=1
model=sg13_lv_pmos
spiceprefix=X
}
C {lab_pin.sym} 150 -190 0 0 {name=p9 sig_type=std_logic lab=ntap}
C {sg13g2_pr/annotate_fet_params.sym} -310 100 0 0 {name=annot2 ref=M4}
C {sg13g2_pr/annotate_fet_params.sym} -90 -150 0 0 {name=annot3 ref=M1}
C {sg13g2_pr/annotate_fet_params.sym} -140 -360 0 0 {name=annot4 ref=M8}
