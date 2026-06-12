v {xschem version=3.4.8RC file_version=1.3}
G {}
K {}
V {}
S {}
F {}
E {}
N 40 -40 40 -20 {lab=GND}
N 220 -40 220 -20 {lab=#net1}
N 100 -20 100 0 {lab=#net1}
N 650 70 650 90 {lab=vdd}
N 650 150 650 170 {lab=GND}
N 620 -110 640 -110 {lab=outp}
N 620 -70 640 -70 {lab=outn}
N 440 -110 460 -110 {lab=inp}
N 440 -70 460 -70 {lab=inn}
N 530 -10 530 10 {lab=GND}
N 100 -20 220 -20 {lab=#net1}
N 100 -40 100 -20 {lab=#net1}
N 530 -190 530 -170 {lab=vdd}
N 550 -230 550 -170 {lab=#net2}
N 550 -230 630 -230 {lab=#net2}
N 630 -230 630 -220 {lab=#net2}
C {vsource_arith.sym} 100 -70 0 0 {name=E1 VOL=v(vdin)/2}
C {lab_pin.sym} 100 -100 1 0 {name=p3 sig_type=std_logic lab=inp}
C {vsource_arith.sym} 220 -70 0 0 {name=E2 VOL=-v(vdin)/2}
C {lab_pin.sym} 220 -100 1 0 {name=p4 sig_type=std_logic lab=inn}
C {lab_pin.sym} 40 -100 1 0 {name=p5 sig_type=std_logic lab=vdin}
C {vsource.sym} 100 30 0 0 {name=V1 value=\{\{vincm\}\} savecurrent=true}
C {gnd.sym} 100 60 0 0 {name=l19 lab=GND}
C {gnd.sym} 40 -20 0 0 {name=l2 lab=GND}
C {devices/code_shown.sym} 710 -120 0 0 {name=NGSPICE only_toplevel=true 
value="
.temp \{\{ temp \}\}
.param mc_ok = \{\{ sigma \}\}
.option SEED = \{\{ seed \}\}
.option method=gear

.control
save v(outp)
save v(outn)
op  
let vd = v(outp)-v(outn)
let ve = (v(outp)+v(outn))/2
echo MY_DATA:$&ve $&vd

quit
.endc
"}
C {simulator_commands_shown.sym} 200 80 0 0 {
name=Libs_Ngspice
simulator=ngspice
only_toplevel=false
value="
.lib cornerMOSlv.lib mos_\{\{ corner_mos \}\}
.lib cornerMOShv.lib mos_\{\{ corner_mos \}\}
"
      }
C {gnd.sym} 530 10 0 0 {name=l4 lab=GND}
C {lab_pin.sym} 440 -110 0 0 {name=p8 sig_type=std_logic lab=inp}
C {lab_pin.sym} 440 -70 0 0 {name=p11 sig_type=std_logic lab=inn}
C {lab_pin.sym} 640 -70 2 0 {name=p25 sig_type=std_logic lab=outn}
C {lab_pin.sym} 640 -110 2 0 {name=p28 sig_type=std_logic lab=outp}
C {vsource.sym} 650 120 0 0 {name=V2 value=\{\{vdd\}\} savecurrent=false}
C {gnd.sym} 650 170 0 0 {name=l1 lab=GND}
C {lab_pin.sym} 650 70 3 1 {name=p6 sig_type=std_logic lab=vdd}
C {vsource.sym} 630 -190 0 0 {name=V5 value=0.35 savecurrent=true}
C {gnd.sym} 630 -160 0 0 {name=l6 lab=GND}
C {vsource.sym} 40 -70 2 0 {name=V4 value=0 savecurrent=true}
C {lab_pin.sym} 530 -190 3 1 {name=p1 sig_type=std_logic lab=vdd}
C {chipify/examples/source_follower/sch/source_follower.sym} 540 -90 0 0 {name=x1}
