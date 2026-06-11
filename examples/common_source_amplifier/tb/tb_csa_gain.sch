v {xschem version=3.4.8RC file_version=1.3}
G {}
K {}
V {}
S {}
F {}
E {}
N -180 -170 -180 -150 {lab=GND}
N 0 -170 0 -150 {lab=#net1}
N -120 -150 -120 -130 {lab=#net1}
N 310 -330 310 -310 {lab=vdd}
N 310 -250 310 -230 {lab=GND}
N 230 -140 250 -140 {lab=outp}
N 230 -100 250 -100 {lab=outn}
N 50 -140 70 -140 {lab=inp}
N 50 -100 70 -100 {lab=inn}
N 140 -220 140 -200 {lab=vdd}
N 140 -40 140 -20 {lab=GND}
N -120 -150 0 -150 {lab=#net1}
N -120 -170 -120 -150 {lab=#net1}
N 160 -250 240 -250 {lab=#net2}
N 240 -250 240 -240 {lab=#net2}
N 160 -250 160 -200 {lab=#net2}
C {vsource_arith.sym} -120 -200 0 0 {name=E1 VOL=v(vdin)/2}
C {lab_pin.sym} -120 -230 1 0 {name=p3 sig_type=std_logic lab=inp}
C {vsource_arith.sym} 0 -200 0 0 {name=E2 VOL=-v(vdin)/2}
C {lab_pin.sym} 0 -230 1 0 {name=p4 sig_type=std_logic lab=inn}
C {lab_pin.sym} -180 -230 1 0 {name=p5 sig_type=std_logic lab=vdin}
C {vsource.sym} -120 -100 0 0 {name=V1 value=\{\{vincm\}\} savecurrent=true}
C {gnd.sym} -120 -70 0 0 {name=l19 lab=GND}
C {gnd.sym} -180 -150 0 0 {name=l2 lab=GND}
C {devices/code_shown.sym} 420 -350 0 0 {name=NGSPICE only_toplevel=true 
value="
.temp \{\{ temp \}\}
.param mc_ok = \{\{ sigma \}\}
.option SEED= \{\{ seed \}\}
.control
save v(outp)
save v(outn)

ac dec 10 1 10000000k

let vdiff = (v(outp) - v(outn))
let gain = mag(vdiff)

meas ac max_gain max gain
meas ac bandwidth when gain=0.707*max_gain fall=1

echo MY_DATA:$&max_gain $&bandwidth
quit
.endc
"}
C {lab_pin.sym} 140 -220 1 0 {name=p1 sig_type=std_logic lab=vdd}
C {gnd.sym} 140 -20 0 0 {name=l4 lab=GND}
C {lab_pin.sym} 50 -140 0 0 {name=p8 sig_type=std_logic lab=inp}
C {lab_pin.sym} 50 -100 0 0 {name=p11 sig_type=std_logic lab=inn}
C {lab_pin.sym} 250 -100 2 0 {name=p25 sig_type=std_logic lab=outn}
C {lab_pin.sym} 250 -140 2 0 {name=p28 sig_type=std_logic lab=outp}
C {vsource.sym} 310 -280 0 0 {name=V2 value=\{\{vdd\}\} savecurrent=false}
C {gnd.sym} 310 -230 0 0 {name=l1 lab=GND}
C {lab_pin.sym} 310 -330 3 1 {name=p6 sig_type=std_logic lab=vdd}
C {simulator_commands_shown.sym} -230 -350 0 0 {
name=Libs_Ngspice1
simulator=ngspice
only_toplevel=false
value="
.lib cornerMOSlv.lib mos_\{\{ corner_mos \}\}
.lib cornerMOShv.lib mos_\{\{ corner_mos \}\}
"
      }
C {chipify/examples/common_source_amplifier/sch/common_source_amplifier.sym} 150 -120 0 0 {name=x1}
C {vsource.sym} 240 -210 0 0 {name=V5 value=0.35 savecurrent=true}
C {gnd.sym} 240 -180 0 0 {name=l6 lab=GND}
C {vsource.sym} -180 -200 0 0 {name=VIN value=ac 1 savecurrent=true}
