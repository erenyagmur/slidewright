# Design session

**Brief:** level 12, medium-hard, introduce trucks blocking the exit row, about 15 moves

**Spec:**
```json
{
  "level_number": 12,
  "difficulty_min": 5.5,
  "difficulty_max": 7.2,
  "target_moves": 15,
  "moves_tolerance": 3,
  "trucks_min": 1,
  "trucks_max": 3,
  "exit_truck": true,
  "mechanic": "A vertical truck sits across the exit row; the player must work out what has to move so it can drop out of the lane."
}
```

## round1: proposals

- **Gatekeeper**: Truck D guards the exit and can only drop once the bottom-right truck H and car J slide away, which needs the left side unpicked first.
- **Two Gates**: Two blockers in the lane (car B, exit truck F); F can only drop once car J slides all the way left.
- **Truck Wall**: Two trucks stand side by side in the exit lane; the inner one needs the row-3 truck and a bottom car to make room.

Solver feedback:
```
Solver report on your variants:

## Gatekeeper: REJECTED
AAAB..
C..B.D
CRRB.D  <- exit
EEF..D
G.FHHH
GII.JJ
- unsolvable: the red car can never reach the exit

## Two Gates: REJECTED
AA..CC
DDEB.F
RREB.F  <- exit
GG.H.F
I..HJJ
IKKK..
min_moves=7 difficulty=5.85 blockers=5 dead_end_ratio=0.529 states=9539
optimal line: E up 1 B up 1 H up 1 J left 3 F down 2 H down 1 R right 4
- optimal solution is 7 moves, target is 12-18

## Truck Wall: REJECTED
AAB.D.
CCB.D.
RR..DF  <- exit
G.HHHF
GII..F
JJ.KK.
min_moves=5 difficulty=4.98 blockers=4 dead_end_ratio=0.491 states=14645
optimal line: F down 1 H left 1 K left 1 D down 3 R right 4
- optimal solution is 5 moves, target is 12-18
- difficulty score 4.98 outside 5.5-7.2

Return corrected or replacement layouts ONLY for the rejected variants. If a level was too short, add a dependency chain (block the blockers); if too long, free one vehicle.
```

## round2: proposals

- **Gatekeeper II**: Same exit truck D, but the deadlock is broken: car C can drop down once the bottom-left is cleared, letting the red car back up and free truck B's column.
- **Two Gates II**: Adds car L in the lane under C: L can only drop after J has cleared row 4, so J's long slide now matters twice.
- **Truck Wall II**: Car N now sits in the lane too and car K starts under truck F, so both trucks compete for the same bottom-row space.

Solver feedback:
```
Solver report on your variants:

## Gatekeeper II: REJECTED
AAAB..
C..B.D
CRRB.D  <- exit
EEF..D
..FHHH
....JJ
min_moves=10 difficulty=5.65 blockers=7 dead_end_ratio=0.342 states=4735
optimal line: B down 1 A right 3 C up 1 R left 1 F up 3 H left 3 J left 3 B down 2 D down 2 R right 4
- optimal solution is 10 moves, target is 12-18
- 4 trucks, brief wants 1-3

## Two Gates II: REJECTED
AA..CC
DDEBLF
RREBLF  <- exit
GG.H.F
I..HJJ
IKKK..
min_moves=8 difficulty=6.03 blockers=6 dead_end_ratio=0.482 states=20592
optimal line: E up 1 B up 1 H up 1 J left 3 L down 2 F down 2 H down 1 R right 4
- optimal solution is 8 moves, target is 12-18

## Truck Wall II: REJECTED
AAB.D.
CCBND.
RR.NDF  <- exit
G.HHHF
GII..F
JJ..KK
min_moves=6 difficulty=5.19 blockers=5 dead_end_ratio=0.425 states=21107
optimal line: N up 1 H left 1 K left 2 D down 3 F down 1 R right 4
- optimal solution is 6 moves, target is 12-18
- difficulty score 5.19 outside 5.5-7.2

Return corrected or replacement layouts ONLY for the rejected variants. If a level was too short, add a dependency chain (block the blockers); if too long, free one vehicle.
```

## round3: proposals

- **Gatekeeper III**: Exit truck D drops only after truck H slides left, and H's path is now blocked by car K, which needs car E out of the way first.
- **Gatekeeper IIIb**: Gatekeeper II with A shrunk to a car and car M parked top-right, so truck B can only go down and the red car has to back up.
- **Gatekeeper IIIc**: Both changes: K blocks truck H's route and M boxes in the top-right corner.

Solver feedback:
```
Solver report on your variants:

## Gatekeeper III: REJECTED
AA.B..
C..B.D
CRRB.D  <- exit
EEF..D
.KFHHH
.K..JJ
- unsolvable: the red car can never reach the exit

## Gatekeeper IIIb: ACCEPTED
AA.BMM
C..B.D
CRRB.D  <- exit
EEF..D
..FHHH
....JJ
min_moves=13 difficulty=6.1 blockers=7 dead_end_ratio=0.36 states=6582
optimal line: F down 1 E right 3 C down 2 R left 1 F up 4 R right 1 C up 1 E left 2 H left 3 J left 3 B down 3 D down 2 R right 3

## Gatekeeper IIIc: REJECTED
AA.BMM
C..B.D
CRRB.D  <- exit
EEF..D
.KFHHH
.K..JJ
- unsolvable: the red car can never reach the exit

Return corrected or replacement layouts ONLY for the rejected variants. If a level was too short, add a dependency chain (block the blockers); if too long, free one vehicle.
```

## round4: proposals

- **Gatekeeper IV**: Gatekeeper IIIb plus car K in the bottom-left corner: truck H's escape route now needs K lifted, which competes with car C for the same column.
- **Gatekeeper IVb**: Gatekeeper IIIb plus car K in the lane at x=4: it can only drop after trucks H and J have cleared the bottom rows.

Solver feedback:
```
Solver report on your variants:

## Gatekeeper IV: REJECTED
AA.BMM
C..B.D
CRRB.D  <- exit
EEF..D
K.FHHH
K...JJ
- unsolvable: the red car can never reach the exit

## Gatekeeper IVb: ACCEPTED
AA.BMM
C..B.D
CRRBKD  <- exit
EEF.KD
..FHHH
....JJ
min_moves=15 difficulty=6.28 blockers=8 dead_end_ratio=0.302 states=14635
optimal line: F down 1 E right 1 C down 3 R left 1 E left 1 F up 4 R right 1 E right 1 C up 2 H left 3 J left 3 B down 3 D down 2 K down 1 R right 3

Return corrected or replacement layouts ONLY for the rejected variants. If a level was too short, add a dependency chain (block the blockers); if too long, free one vehicle.
```

## Accepted levels

### Gatekeeper IIIb
```
AA.BMM
C..B.D
CRRB.D  <- exit
EEF..D
..FHHH
....JJ
```
13 moves · difficulty 6.1 · 7 blockers · win rate 48% · churn risk 8%

*Why it works:* The exit lane holds two trucks, B and D, and both can only leave by dropping into the bottom rows, which truck H and car J are sitting on. H can only slide left once car F clears column 2, and F can only get out by going up through the red car's row. That forces the counter-intuitive opening: move the red car backwards to make room.

*What it teaches:* Introduces trucks blocking the exit row, and the idea that the red car can be its own blocker. Players learn to read a dependency chain backwards from the exit (D needs the corner, the corner needs H, H needs F) instead of attacking the nearest obstacle.

### Gatekeeper IVb
```
AA.BMM
C..B.D
CRRBKD  <- exit
EEF.KD
..FHHH
....JJ
```
15 moves · difficulty 6.28 · 8 blockers · win rate 36% · churn risk 19%

*Why it works:* Builds on IIIb with car K standing in the lane next to exit truck D. K can only leave downwards, so B, D and K all have to drop through the same bottom-right gap that H and J vacate. The left-side shuffle (C, E, F and the red car backing up) also gets one step longer, because C now has to drop all the way to the bottom.

*What it teaches:* Ordering under pressure: clear the bottom rows once, then let three vehicles fall through in sequence. It's the harder follow-up to IIIb, so a player who has just learned that backing up the red car is allowed has to apply it again inside a longer chain.
