v {xschem version=3.4.8RC file_version=1.3}
G {}
K {}
V {}
S {}
F {}
E {}
N -10 -210 -10 -190 {lab=#net1}
N -130 -190 -130 -170 {lab=#net1}
N 420 20 420 40 {lab=vdd}
N 420 100 420 120 {lab=GND}
N 280 -150 300 -150 {lab=outn}
N 280 -190 300 -190 {lab=outp}
N 100 -190 120 -190 {lab=inp}
N 100 -150 120 -150 {lab=inn}
N 190 -270 190 -250 {lab=vdd}
N 190 -90 190 -70 {lab=GND}
N -130 -190 -10 -190 {lab=#net1}
N -130 -210 -130 -190 {lab=#net1}
N -240 -180 -240 -160 {lab=GND}
N 210 -310 290 -310 {lab=#net2}
N 290 -310 290 -300 {lab=#net2}
N 210 -310 210 -250 {lab=#net2}
C {vsource_arith.sym} -130 -240 0 0 {name=E1 VOL=v(vdin)/2}
C {lab_pin.sym} -130 -270 1 0 {name=p3 sig_type=std_logic lab=inp}
C {vsource_arith.sym} -10 -240 0 0 {name=E2 VOL=-v(vdin)/2}
C {lab_pin.sym} -10 -270 1 0 {name=p4 sig_type=std_logic lab=inn}
C {vsource.sym} -130 -140 0 0 {name=V1 value=\{\{vincm\}\} savecurrent=true}
C {gnd.sym} -130 -110 0 0 {name=l19 lab=GND}
C {devices/code_shown.sym} 480 -460 0 0 {name=NGSPICE only_toplevel=true 
value="
.temp \{\{ temp \}\}
.param mc_ok = \{\{ sigma \}\}
.option SEED = \{\{ seed \}\}
.option method=gear

.control
save v(outp)
save v(outn)
save v(vdin)

dc V10 0.001 1.5 0.001
let vd = outp-outn
let dc_gain = vd / v(vdin)
let dc_gain_db = 20 * log10(dc_gain)
let linear_gain_db = dc_gain_db[0]
let p1db_threshold = linear_gain_db - 1
meas dc p1db WHEN dc_gain_db=$&p1db_threshold

echo MY_DATA:$&dc1.p1db

quit
.endc
"}
C {simulator_commands_shown.sym} -10 60 0 0 {
name=Libs_Ngspice
simulator=ngspice
only_toplevel=false
value="
.lib cornerMOSlv.lib mos_\{\{ corner_mos \}\}
.lib cornerMOShv.lib mos_\{\{ corner_mos \}\}
"
      }
C {lab_pin.sym} 190 -270 1 0 {name=p1 sig_type=std_logic lab=vdd}
C {gnd.sym} 190 -70 0 0 {name=l4 lab=GND}
C {lab_pin.sym} 100 -190 0 0 {name=p8 sig_type=std_logic lab=inp}
C {lab_pin.sym} 100 -150 0 0 {name=p11 sig_type=std_logic lab=inn}
C {lab_pin.sym} 300 -150 2 0 {name=p25 sig_type=std_logic lab=outn}
C {lab_pin.sym} 300 -190 2 0 {name=p28 sig_type=std_logic lab=outp}
C {vsource.sym} 420 70 0 0 {name=V2 value=\{\{vdd\}\} savecurrent=false}
C {gnd.sym} 420 120 0 0 {name=l1 lab=GND}
C {lab_pin.sym} 420 20 3 1 {name=p6 sig_type=std_logic lab=vdd}
C {lab_pin.sym} -240 -240 1 0 {name=p14 sig_type=std_logic lab=vdin}
C {gnd.sym} -240 -160 0 0 {name=l9 lab=GND}
C {vsource.sym} -240 -210 0 0 {name=V10 value=0 savecurrent=true}
C {chipify/examples/common_source_amplifier/sch/common_source_amplifier.sym} 200 -170 0 0 {name=x1}
C {vsource.sym} 290 -270 0 0 {name=V5 value=0.35 savecurrent=true}
C {gnd.sym} 290 -240 0 0 {name=l6 lab=GND}
