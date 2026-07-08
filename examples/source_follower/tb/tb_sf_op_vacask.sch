v {xschem version=3.4.8RC file_version=1.3}
G {}
K {}
V {}
S {}
F {}
E {}
N 100 -20 100 0 {lab=#net1}
N 650 70 650 90 {lab=vdd}
N 650 150 650 170 {lab=GND}
N 620 -110 640 -110 {lab=outp}
N 620 -70 640 -70 {lab=outn}
N 530 -10 530 10 {lab=GND}
N 100 -20 220 -20 {lab=#net1}
N 530 -190 530 -170 {lab=vdd}
N 550 -230 550 -170 {lab=#net2}
N 550 -230 630 -230 {lab=#net2}
N 630 -230 630 -220 {lab=#net2}
N 100 -110 460 -110 {lab=#net1}
N 100 -110 100 -20 {lab=#net1}
N 220 -70 460 -70 {lab=#net1}
N 220 -70 220 -20 {lab=#net1}
C {vsource.sym} 100 30 0 0 {name=V1 value="dc=\{\{vincm\}\}" savecurrent=true}
C {gnd.sym} 100 60 0 0 {name=l19 lab=GND}
C {gnd.sym} 530 10 0 0 {name=l4 lab=GND}
C {vsource.sym} 650 120 0 0 {name=V2 value="dc=\{\{vdd\}\}" savecurrent=false}
C {gnd.sym} 650 170 0 0 {name=l1 lab=GND}
C {lab_pin.sym} 650 70 3 1 {name=p6 sig_type=std_logic lab=vdd}
C {vsource.sym} 630 -190 0 0 {name=V5 value="dc=0.35" savecurrent=true}
C {gnd.sym} 630 -160 0 0 {name=l6 lab=GND}
C {lab_pin.sym} 530 -190 3 1 {name=p1 sig_type=std_logic lab=vdd}
C {chipify/examples/source_follower/sch/source_follower.sym} 540 -90 0 0 {name=x1}
C {simulator_commands_shown.sym} 770 40 0 0 {name=Commands
simulator=vacask
only_toplevel=false 
value="
control
  options temp=\{\{temp\}\}
  save all
  options reltol=1e-6
  analysis op1 op
endc
"}
C {simulator_commands_shown.sym} 0 210 0 0 {
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
C {lab_pin.sym} 640 -110 0 1 {name=p2 sig_type=std_logic lab=outp}
C {lab_pin.sym} 640 -70 0 1 {name=p3 sig_type=std_logic lab=outn}
