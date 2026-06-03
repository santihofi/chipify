v {xschem version=3.4.8RC file_version=1.3}
G {}
K {}
V {}
S {}
F {}
E {}
N -190 -210 -190 -190 {lab=GND}
N -10 -210 -10 -190 {lab=#net1}
N -130 -190 -130 -170 {lab=#net1}
N 650 70 650 90 {lab=vdd}
N 650 150 650 170 {lab=GND}
N 760 70 760 90 {lab=vss}
N 760 150 760 170 {lab=GND}
N 320 -150 340 -150 {lab=out}
N 110 -180 130 -180 {lab=inp}
N 110 -120 130 -120 {lab=inn}
N 220 -270 220 -250 {lab=vdd}
N 220 -50 220 -30 {lab=GND}
N 250 -270 250 -250 {lab=#net2}
N 250 -350 250 -330 {lab=vdd}
N -130 -190 -10 -190 {lab=#net1}
N -130 -210 -130 -190 {lab=#net1}
C {vsource_arith.sym} -130 -240 0 0 {name=E1 VOL=v(vdin)/2}
C {lab_pin.sym} -130 -270 1 0 {name=p3 sig_type=std_logic lab=inp}
C {vsource_arith.sym} -10 -240 0 0 {name=E2 VOL=-v(vdin)/2}
C {lab_pin.sym} -10 -270 1 0 {name=p4 sig_type=std_logic lab=inn}
C {lab_pin.sym} -190 -270 1 0 {name=p5 sig_type=std_logic lab=vdin}
C {vsource.sym} -130 -140 0 0 {name=V1 value=\{\{vincm\}\} savecurrent=true}
C {gnd.sym} -130 -110 0 0 {name=l19 lab=GND}
C {gnd.sym} -190 -190 0 0 {name=l2 lab=GND}
C {devices/code_shown.sym} 400 -350 0 0 {name=NGSPICE only_toplevel=true 
value="
.temp \{\{ temp \}\}
.param mc_ok = \{\{ sigma \}\}
.option SEED= \{\{ seed \}\}
.control
save v(out)

ac dec 10 1 10000000k

let gain = mag(out)

meas ac max_gain max gain
meas ac bandwidth when gain=0.707*max_gain fall=1

echo MY_DATA:$&max_gain $&bandwidth
quit
.endc
"}
C {lab_pin.sym} 220 -270 1 0 {name=p1 sig_type=std_logic lab=vdd}
C {gnd.sym} 220 -30 0 0 {name=l4 lab=GND}
C {lab_pin.sym} 110 -180 0 0 {name=p8 sig_type=std_logic lab=inp}
C {lab_pin.sym} 110 -120 0 0 {name=p11 sig_type=std_logic lab=inn}
C {lab_pin.sym} 340 -150 2 0 {name=p28 sig_type=std_logic lab=out}
C {vsource.sym} 650 120 0 0 {name=V2 value=\{\{vdd\}\} savecurrent=false}
C {gnd.sym} 650 170 0 0 {name=l1 lab=GND}
C {lab_pin.sym} 650 70 3 1 {name=p6 sig_type=std_logic lab=vdd}
C {vsource.sym} 760 120 0 0 {name=V3 value=0 savecurrent=false}
C {gnd.sym} 760 170 0 0 {name=l5 lab=GND}
C {lab_pin.sym} 760 70 3 1 {name=p7 sig_type=std_logic lab=vss}
C {vsource.sym} -190 -240 2 0 {name=V4 value=ac 1 savecurrent=true}
C {isource.sym} 250 -300 0 0 {name=I0 value=\{\{ibias\}\}}
C {lab_pin.sym} 250 -350 1 0 {name=p10 sig_type=std_logic lab=vdd}
C {simulator_commands_shown.sym} 170 80 0 0 {
name=Libs_Ngspice1
simulator=ngspice
only_toplevel=false
value="
.lib cornerMOSlv.lib mos_\{\{ corner_mos \}\}
.lib cornerMOShv.lib mos_\{\{ corner_mos \}\}
.lib cornerRES.lib res_typ
"
      }
C {chipify/examples/ota/sch/ota.sym} 220 -150 0 0 {name=x1}
