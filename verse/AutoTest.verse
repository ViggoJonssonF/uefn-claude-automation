using { /Fortnite.com/Characters }
using { /Fortnite.com/Playspaces }
using { /Verse.org }
using { /Verse.org/Simulation }

# --- In-game AutoTest harness (template) -----------------------------------------------------------
# Drop this file anywhere in your project's Verse source, keep the file name `AutoTest.verse`
# (uefn_playtest.py finds it by name), then start it from a device that is always in your level:
#
#     OnBegin<override>()<suspends>:void=
#         if (AutoTestEnabled?):
#             spawn{ RunAutoTests(GetPlayspace()) }
#
# uefn_playtest.py flips AutoTestEnabled to true, compiles, runs a play-in-client session, reads the
# lines below from the editor log, and ALWAYS flips it back to false afterwards.
#
# The log-line contract (do not change the prefixes without changing uefn_playtest.py):
#
#   AUTOTEST: BEGIN
#   AUTOTEST: PASS <id> | <detail>
#   AUTOTEST: FAIL <id> | <detail>
#   AUTOTEST: SKIP <id> | <reason>
#   AUTOTEST: INFO <anything>
#   AUTOTEST: END passed=<n> failed=<n>
#
# Writing scenarios:
#  * Drive the game through the SAME code path a player triggers - call the handler your button,
#    trigger or interactable calls, don't set state directly. For step buttons, give the button
#    component a public `SimulateStep(Player)` that signals the same event a real step signals.
#  * Put the observed values in the detail so a FAIL can be diagnosed from the log alone.
#  * Wait on state (with a cap), not on fixed sleeps, where your game exposes the state.
#  * SKIP when a precondition is legitimately missing instead of failing.
#  * Tests mutate real playtest save data - snapshot anything you change and restore it before END.
#  * `logic` can't be interpolated into strings - use YesNo().
#
# Keep AutoTestEnabled = false in anything you share or publish.
AutoTestEnabled<public> : logic = false

autotest_report<public> := class:
    var Passed<public> : int = 0
    var Failed<public> : int = 0

    Check<public>(Id:string, Ok:logic, Detail:string):void=
        if (Ok?):
            set Passed += 1
            Print("AUTOTEST: PASS {Id} | {Detail}")
        else:
            set Failed += 1
            Print("AUTOTEST: FAIL {Id} | {Detail}")

    Skip<public>(Id:string, Reason:string):void=
        Print("AUTOTEST: SKIP {Id} | {Reason}")

    Info<public>(Message:string):void=
        Print("AUTOTEST: INFO {Message}")

YesNo<public>(Value:logic)<computes>:string =
    if (Value?) then "yes" else "no"

# "a, b, c (+4 more)" - for listing offenders in a FAIL detail without flooding the log.
JoinFirst<public>(Items:[]string, Limit:int)<transacts>:string =
    var Out : string = ""
    for (Index -> Item : Items, Index < Limit):
        set Out = if (Index = 0) then Item else Out + ", " + Item
    if (Items.Length > Limit) then Out + " (+{Items.Length - Limit} more)" else Out

RunAutoTests<public>(Playspace:fort_playspace)<suspends>:void=
    Print("AUTOTEST: BEGIN")
    Report := autotest_report{}
    var MaybePlayer : ?player = false
    var Waited : float = 0.0
    loop:
        if (First := Playspace.GetPlayers()[0]):
            set MaybePlayer = option{First}
            break
        if (Waited > 60.0):
            break
        Sleep(0.5)
        set Waited += 0.5
    if (Player := MaybePlayer?):
        RunAutoTestScenarios(Player, Report)
    else:
        Report.Check("T00-player", false, "no player joined within 60 s")
    Print("AUTOTEST: END passed={Report.Passed} failed={Report.Failed}")

# --- Your scenarios go here ------------------------------------------------------------------------
RunAutoTestScenarios(Player:player, Report:autotest_report)<suspends>:void=
    # Example T01: wait (capped) for the player's character to exist - the pattern for any
    # "wait until the game reaches state X" step.
    var Waited : float = 0.0
    loop:
        if (Player.GetFortCharacter[]):
            break
        if (Waited > 30.0):
            break
        Sleep(0.5)
        set Waited += 0.5
    HasCharacter := if (Player.GetFortCharacter[]) then true else false
    Report.Check("T01-character", HasCharacter, "character present={YesNo(HasCharacter)} after {Waited} s")

    # Example T02: an invariant check with the observed value in the detail.
    #   Before := GetMoney(Player)
    #   Spent := TrySpend(Player, Before + 1)
    #   Report.Check("T02-overspend-refused", logic{not Spent?, GetMoney(Player) = Before},
    #       "refused={YesNo(logic{not Spent?})} balance {Before} -> {GetMoney(Player)}")
