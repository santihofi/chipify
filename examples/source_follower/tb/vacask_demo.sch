v {xschem version=3.4.8RC file_version=1.3}
G {}
K {}
V {}
S {}
F {}
E {}
N 30 -580 30 -530 {lab=vcc}
N 220 -580 360 -580 {lab=vcc}
N 360 -580 360 -460 {lab=vcc}
N 140 -580 140 -560 {lab=vcc}
N 220 -580 220 -560 {lab=vcc}
N 140 -480 140 -460 {lab=c}
N 220 -480 220 -460 {lab=c}
N 140 -480 220 -480 {lab=c}
N 140 -370 140 -350 {lab=e}
N 140 -370 220 -370 {lab=e}
N 220 -400 220 -370 {lab=e}
N 30 -430 30 -380 {lab=b}
N 30 -430 100 -430 {lab=b}
N 140 -290 140 -270 {lab=GND}
N 30 -270 140 -270 {lab=GND}
N 30 -320 30 -270 {lab=GND}
N 140 -270 360 -270 {lab=GND}
N 360 -400 360 -270 {lab=GND}
N 140 -270 140 -260 {lab=GND}
N 30 -580 140 -580 {lab=vcc}
N 140 -580 220 -580 {lab=vcc}
N 140 -500 140 -480 {lab=c}
N 220 -500 220 -480 {lab=c}
N 140 -390 140 -370 {lab=e}
N 30 -470 30 -430 {lab=b}
N 140 -430 160 -430 {lab=e}
N 160 -430 160 -390 {lab=e}
N 140 -390 160 -390 {lab=e}
N 140 -400 140 -390 {lab=e}
C {simulator_commands_shown.sym} 420 -110 0 0 {name=Commands
simulator=vacask
only_toplevel=false 
value="
control
  options reltol=1e-6
  analysis op1 op
  analysis tran1 tran stop=1u step=1n
endc
"}
C {res.sym} 30 -500 0 0 {name=R1
value=47k
footprint=1206
device=resistor
m=1}
C {res.sym} 140 -320 0 0 {name=R2
value=470
footprint=1206
device=resistor
m=1}
C {capa.sym} 140 -530 0 0 {name=C1
m=1
value=20p
footprint=1206
device="ceramic capacitor"}
C {capa.sym} 220 -430 0 0 {name=C2
m=1
value=10p
footprint=1206
device="ceramic capacitor"}
C {capa.sym} 30 -350 0 0 {name=C3
m=1
value=1n
footprint=1206
device="ceramic capacitor"}
C {ind.sym} 220 -530 0 0 {name=L1
m=1
value=100n
footprint=1206
device=inductor}
C {vsource.sym} 360 -430 0 0 {name=Vcc value="dc=1.5" savecurrent=false}
C {gnd.sym} 140 -260 0 0 {name=l2 lab=GND}
C {lab_wire.sym} 30 -430 0 0 {name=p1 sig_type=std_logic lab=b
}
C {lab_wire.sym} 140 -480 0 0 {name=p2 sig_type=std_logic lab=c
}
C {lab_wire.sym} 140 -370 0 0 {name=p3 sig_type=std_logic lab=e
}
C {lab_wire.sym} 180 -580 0 0 {name=p4 sig_type=std_logic lab=vcc
}
C {simulator_commands_shown.sym} -500 -140 0 0 {
name=Libs_VACASK
simulator=vacask
only_toplevel=false
value="
include \\"/foss/pdks/ihp-sg13g2/libs.tech/vacask/models/sg13g2_vacask_common.lib\\"
include \\"/foss/pdks/ihp-sg13g2/libs.tech/vacask/models/cornerMOSlv.lib\\" section=mos_tt
include \\"/foss/pdks/ihp-sg13g2/libs.tech/vacask/models/cornerRES.lib\\" section=res_typ
include \\"/foss/pdks/ihp-sg13g2/libs.tech/vacask/models/cornerCAP.lib\\" section=cap_typ
include \\"/foss/pdks/ihp-sg13g2/libs.tech/vacask/models/cornerDIO.lib\\" section=dio_tt


"
      }
C {sg13_lv_nmos.sym} 120 -430 0 0 {name=M1
l=0.13u
w=0.15u
ng=1
m=1
model=sg13_lv_nmos
spiceprefix=X
}
