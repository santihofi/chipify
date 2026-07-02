v {xschem version=3.4.8RC file_version=1.3}
G {}
K {}
V {}
S {}
F {}
E {}
N 310 -530 310 -410 {lab=#net1}
N 0 -220 90 -220 {lab=GND}
N 120 -220 310 -220 {lab=GND}
N 310 -350 310 -220 {lab=GND}
N 90 -220 90 -210 {lab=GND}
N 90 -450 90 -410 {lab=out}
N 90 -350 90 -220 {lab=GND}
N 90 -530 90 -510 {lab=#net1}
N 90 -530 310 -530 {lab=#net1}
N 0 -270 0 -220 {lab=GND}
N 0 -380 0 -330 {lab=#net2}
N 0 -380 50 -380 {lab=#net2}
N 90 -380 120 -380 {lab=GND}
N 120 -380 120 -220 {lab=GND}
N 90 -220 120 -220 {lab=GND}
C {simulator_commands_shown.sym} 420 -320 0 0 {name=Commands
simulator=vacask
only_toplevel=false 
value="
control
  options temp=\{\{temp\}\}
  options reltol=1e-6
  analysis nmos op
  //analysis tran1_nmos tran stop=5m step=10u
endc
"}
C {res.sym} 90 -480 0 0 {name=R1
value=10k
footprint=1206
device=resistor
m=1}
C {vsource.sym} 310 -380 0 0 {name=Vcc value="dc=\{\{vdd\}\}" savecurrent=false}
C {gnd.sym} 90 -210 0 0 {name=l2 lab=GND}
C {simulator_commands_shown.sym} 0 -130 0 0 {
name=Libs_VACASK
simulator=vacask
only_toplevel=false
value="
include \\"/foss/pdks/ihp-sg13g2/libs.tech/vacask/models/sg13g2_vacask_common.lib\\"
include \\"/foss/pdks/ihp-sg13g2/libs.tech/vacask/models/cornerMOSlv.lib\\" section=mos_\{\{corner_mos\}\}
include \\"/foss/pdks/ihp-sg13g2/libs.tech/vacask/models/cornerRES.lib\\" section=res_typ
include \\"/foss/pdks/ihp-sg13g2/libs.tech/vacask/models/cornerCAP.lib\\" section=cap_typ

"
      }
C {sg13_lv_nmos.sym} 70 -380 0 0 {name=M1
l=0.13u
w=0.15u
ng=1
m=1
model=sg13_lv_nmos
spiceprefix=X
}
C {vsource.sym} 0 -300 0 0 {name=Vcc1 value="type=\\"sine\\" sinedc=1 ampl=0.1 freq=1k" savecurrent=false}
C {lab_wire.sym} 90 -420 0 0 {name=p3 sig_type=std_logic lab=out
}
