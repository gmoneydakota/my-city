import json
P=[];J=[]
def part(id,name,shape,size,pos,role,color="#999999",material="plastic",parent=None,rot=None,**k):
    d=dict(id=id,name=name,shape=shape,size=size,pos=pos,color=color,material=material,parent=parent,role=role)
    if rot:d["rot"]=rot
    d.update(k);P.append(d)
W="#d8d2c4"
part("wall_l","Left wall","box",dict(w=500,h=2400,d=100),[-700,1200,0],"Wall beside the opening; carries the cam lever",W,"stone")
part("wall_r","Right wall (parking side)","box",dict(w=1050,h=2400,d=100),[975,1200,0],"Wall the open door parks against",W,"stone")
part("header","Header","box",dict(w=900,h=300,d=100),[0,2250,0],"Closes the wall above the opening",W,"stone")
for n,s,p in [("left",dict(w=30,h=2100,d=10),[-465,1050,55]),("right",dict(w=30,h=2100,d=10),[465,1050,55]),("top",dict(w=900,h=30,d=10),[0,2085,55])]:
    part("gasket_"+n,"Frame gasket "+n,"box",s,p,"Rubber seal the door is pressed onto when closed","#222222","rubber")
part("floor_plate","Floor guide plate","box",dict(w=2000,h=5,d=110),[500,2.5,95],"Flat floor plate (no step) that guides the bottom pin","#777777","metal")
part("lip_a","Floor lip inner","box",dict(w=2000,h=15,d=10),[500,7.5,45],"Wall of the guide groove","#777777","metal",parent="floor_plate")
part("lip_b","Floor lip outer","box",dict(w=2000,h=15,d=10),[500,7.5,145],"Wall of the guide groove","#777777","metal",parent="floor_plate")
for i,x in enumerate([-400,500,1400]):
    part(f"bracket{i}","Rail guide block %d"%(i+1),"box",dict(w=60,h=70,d=50),[x,2205,75],"Fixed block bolted to the wall; the rail slides in/out through it","#555555","metal")
part("rail","Pop-out rail","box",dict(w=2000,h=50,d=30),[500,2205,100],"Overhead rail; pushed 40 mm outward to lift the door off its seal","#8a8f98","metal")
part("trolley_a","Trolley A","box",dict(w=120,h=80,d=40),[-250,2140,90],"Roller carriage hanging the door from the rail","#444444","metal",parent="rail")
part("trolley_b","Trolley B","box",dict(w=120,h=80,d=40),[250,2140,90],"Roller carriage hanging the door from the rail","#444444","metal",parent="trolley_a")
part("panel","Door panel","box",dict(w=960,h=2080,d=40),[0,1060,78],"Flat plug door, sealed against the gasket when closed","#3f6e8c","paint",parent="trolley_b")
part("window","Glass window","box",dict(w=300,h=900,d=44),[0,1300,78],"Vision panel","#a8d8ea","glass",parent="panel")
part("pull","Pull bar","cylinder",dict(r=12,h=600),[380,1050,115],"Grab handle for sliding","#c0c0c0","metal",parent="panel")
for i,y in enumerate([800,1300]):
    part(f"pullpost{i}","Pull post","cylinder",dict(r=8,h=30),[380,y,103],"Stand-off","#c0c0c0","metal",parent="panel",rot=[90,0,0])
part("dropseal","Bottom brush seal","box",dict(w=960,h=22,d=30),[0,11,78],"Closes the 20 mm floor gap","#222222","rubber",parent="panel")
part("pin","Floor guide pin","cylinder",dict(r=8,h=40),[0,25,78],"Keeps the bottom of the door in line in the groove","#c0c0c0","metal",parent="panel")
part("hub","Cam shaft hub","cylinder",dict(r=24,h=30),[-700,1050,65],"Shaft that turns the cam behind the wall","#555555","metal",rot=[90,0,0])
part("lever","Cam lever","box",dict(w=150,h=26,d=20),[-625,1050,85],"Lever: lift 90 deg to push the door out","#d33a2c","plastic",parent="hub")
J.append(dict(id="handle",name="Cam lever",type="revolute",part="hub",pivot=[-700,1050,65],axis=[0,0,1],min=0,max=90))
J.append(dict(id="popout",name="Door pop-out",type="prismatic",part="rail",axis=[0,0,1],min=0,max=40,follows=dict(joint="handle",ratio=0.4444,offset=0)))
J.append(dict(id="slide",name="Door slide",type="prismatic",part="trolley_a",axis=[1,0,0],min=0,max=960,period=6))
m=dict(format="agent-city-cad/1",name="Pop-Out Plug Door",
description="A sealed flat door that a cam lever pushes 40 mm off its gasket, then slides sideways along the outside of the wall on an overhead rail: no swing space, no floor track.",
units="mm",
how_it_works=["Closed, the flat door is squeezed against a rubber gasket all round, so it is draughtproof and quiet.","Lift the red cam lever 90 degrees. A cam behind the wall turns that rotation into a 40 mm straight push, moving the rail and the door outward.","The door has now left the gasket, so nothing rubs when it moves: that is why it seals better than a normal sliding door.","Pull the bar sideways; two roller trolleys carry the weight along the rail and a pin in the floor groove stops the bottom swinging.","The door parks against the wall beside the opening, leaving a full 900 mm step-free gap.","Lever down: the cam pulls the door back onto the gasket. Same idea as train and aircraft plug doors."],
assumptions=["Cam/bell-crank behind the wall is simplified to the lever's follows link.","Door is shown closed at rest; pop first (lever), then slide.","Wall is 100 mm; rail passes through guide blocks."],
parts=P,joints=J)
json.dump(m,open("outputs/job-8/model.json","w"),indent=1)
