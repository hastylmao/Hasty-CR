"""Cheap, public-state safeguards. They do not guess unknown unit traits."""
# Thresholds/offsets below are heuristics, UNVERIFIED LIVE. Paired simulator
# controls validate their selected cases, not game-wide balance. Changes need
# the paired controls plus logged friendly tests; these are not game constants.
import math


def own(x,y,team):
    return (x,32000-y) if team==0 else (18000-x,y)


def threats(state,team,sub):
    out=[]
    for e in state['entities']:
        if e[1]==team or e[4]>=0 or e[7]<=0 or e[2]==1:continue
        x,y=own(e[5]/sub,e[6]/sub,team)
        if y>=14500:out.append((x,y,e[7],bool(e[10]),False))
    for e in state.get('unknown_units',[]):
        if e['team']==team or e['hp']<=0:continue
        x,y=own(e['x'],e['y'],team)
        if y>=14500:out.append((x,y,e['hp'],None,True))
    return out


def defence_plan(state,team,sub,catalogue,blocked,spendable):
    enemies=threats(state,team,sub)
    if not enemies:return None
    # Bound clustering work even if the reader reports thousands of objects.
    enemies=sorted(enemies,key=lambda e:-e[1])[:96]
    clusters=[[e for e in enemies if (e[0]-c[0])**2+(e[1]-c[1])**2<=3500**2] for c in enemies]
    cluster=max(clusters,key=lambda es:(len(es),sum(e[2] for e in es)))
    x=sum(e[0] for e in cluster)/len(cluster);y=sum(e[1] for e in cluster)/len(cluster)
    unknown=any(e[4] for e in cluster)
    if len(cluster)<5 and not (unknown and y>=19000 and sum(e[2] for e in cluster)>=1000):return None
    # Do not keep spending on a cluster already covered by a substantial defence.
    allied_hp=0
    for e in state['entities']:
        if e[1]!=team or e[4]>=0 or e[7]<=0:continue
        name=catalogue[e[3]][0] if 0<=e[3]<len(catalogue) else ''
        both={'Musketeer','IceSpirits'}
        ground={'Cannon','Skeletons'}
        needs_air=unknown or any(c[3] for c in cluster)
        if name not in both and (needs_air or name not in ground):continue
        ax,ay=own(e[5]/sub,e[6]/sub,team)
        if (ax-x)**2+(ay-y)**2<4500**2:allied_hp+=e[7]
    if allied_hp>=max(1200,sum(e[2] for e in cluster)*1.5):return None
    p=state['players'][team]
    choices=[]
    for slot,card in enumerate(p['hand']):
        if slot in blocked or card<0 or spendable<p['hand_costs'][slot]*1000:continue
        name=catalogue[card][0]
        # Log only when every target is known ground. Unknowns get both-target counters.
        ground=all(e[3] is False for e in cluster)
        if name=='Log' and ground and max(e[0] for e in cluster)-min(e[0] for e in cluster)<=3600:
            choices.append((0,slot,x,min(31000,y+2500),name))
        elif name=='Fireball' and (len(cluster)>=8 or unknown or any(e[3] for e in cluster)):
            choices.append((4 if unknown and len(cluster)<3 else 1,slot,x,y,name))
        elif name=='IceSpirits' and len(cluster)>=5:
            choices.append((2,slot,x,min(31000,y+2200),name))
        elif name=='Musketeer' and (unknown or any(e[3] for e in cluster)):
            choices.append((3,slot,x,min(30500,y+4000),name))
    if not choices:return None
    _,slot,x,y,name=min(choices)
    tx=max(0,min(17,int(x//1000)));ty=max(0,min(31,int(y//1000)))
    tiles=[(tx,ty)]
    # Nearby alternatives let the actual engine legality check decide.
    tiles += [(max(0,min(17,tx+dx)),max(0,min(31,ty+dy)))
              for dx,dy in [(0,1),(-1,0),(1,0),(0,2),(-2,0),(2,0)]]
    return {'slot':slot,'tiles':tiles,'reason':'unknown-threat' if unknown else 'swarm',
            'count':len(cluster),'hp':sum(e[2] for e in cluster),'card':name,
            'centre':(sum(e[0] for e in cluster)/len(cluster),sum(e[1] for e in cluster)/len(cluster))}


def defence_order(plan,model_order):
    order=[ty*18+tx for tx,ty in plan['tiles']]
    if plan['card']=='Fireball':
        # Keep a nearby model aim ahead of an approaching cluster: aiming only
        # at its old centre can miss fast troops during input/projectile delay.
        x,y=plan['centre']
        for t in list(model_order)[:10]:
            tx=(int(t)%18)*1000+500;ty=(int(t)//18)*1000+500
            if abs(tx-x)<=1500 and 0<=ty-y<=4000:
                order=[int(t)]+order;break
    return list(dict.fromkeys(order))


def hog_order(order,state,team,sub,slot,check):
    enemy=state['players'][1-team]
    hp=enemy['tower_hp'];mx=enemy['tower_max_hp']
    if (hp[1]>0)==(hp[2]>0) or hp[0]<=max(600,mx[0]*.2):return list(order),None
    # Own-frame left princess corresponds to world right when we are red.
    alive_world=1 if hp[1]>0 else 2
    alive_left=(alive_world==1) if team==0 else (alive_world==2)
    target_x=3500 if alive_left else 14500
    def aims_at_princess(t):
        x=(int(t)%18)*1000+500;y=(int(t)//18)*1000+500
        princess=math.hypot(x-target_x,y-6500)-1000
        king=math.hypot(x-9000,y-3000)-1400
        return princess<king
    preferred=[int(t) for t in order if aims_at_princess(t)]
    rest=[int(t) for t in order if not aims_at_princess(t)]
    # If the policy's first legal drop already targets the surviving princess,
    # keep it. A pocket can expose the Hog to both towers and be worse.
    for t in order:
        ox,oy=(int(t)%18)*1000+500,(int(t)//18)*1000+500
        wx,wy=(ox,32000-oy) if team==0 else (18000-ox,oy)
        if check.check_deploy(team,slot,wx*sub,wy*sub)==0:
            if aims_at_princess(t):return preferred+rest,'surviving-princess'
            break
    # Explicitly consider legal enemy-half pocket positions. Keep only positions
    # closer to the surviving princess than the king, rather than blind pocket taps.
    pocket=[]
    for ty in range(6,16):
        for tx in range(18):
            tile=ty*18+tx
            if not aims_at_princess(tile):continue
            ox,oy=tx*1000+500,ty*1000+500
            wx,wy=(ox,32000-oy) if team==0 else (18000-ox,oy)
            if check.check_deploy(team,slot,wx*sub,wy*sub)==0:
                pocket.append(tile)
    pocket.sort(key=lambda t:math.hypot((t%18)*1000+500-target_x,(t//18)*1000+500-6500))
    return list(dict.fromkeys(pocket[:3]+preferred+rest)),'surviving-princess'
