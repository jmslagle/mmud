# `config_ini_load` @ `0x004361da`  (+ `config_ini_save @0x43af25`, `bbs_profile_load @0x41078d`)

Loads every per-character user setting from the `.ini` via **`GetPrivateProfileStringA`** into a temp
buffer, then `atoi` for numerics (there are **zero `GetPrivateProfileIntA` calls** — all 381 reads are
string reads). `bbs_profile_load` does the same for the per-BBS profile. This is the authoritative list
of MegaMud's user-configurable surface — the 9-tab settings property sheet
(`settings_propertysheet_open @0x47a7a0`) edits exactly these.

Offsets are off the character/game-state struct (`param_1`). Keys grouped by the settings page that owns
them (page proc addresses in parens).

```text
General/Logon  (settings_general_page_proc @0x45abe0 + bbs_profile_load @0x41078d)
  per-char: BbsName(+0x2321) UserID(+0x2bfc) Password IsMudop StartTask AutoConnect StatLine
            CmdSplitChar DefaultLoop(+0x55c7)
  per-BBS:  PhoneNum/PhoneAlt TelnetAddr(+0x158) TelnetPort(+0x154,def 23)
            LogonPrompt0..19(+0x1a9 stride0x29 def"--Unused--") LogonReply0..19(+0x4dd)
            MenuPrompt(+0x811 def"[MAJORMUD]:") LogoffCmd RelogCmd(def"relog") AnsiCmd(def"=a")
            Speech/BroadcastPrefix Logon/Logoff/ShutDown/BroadcastMsg Global1-3Msg/Two
            MaxInputSize(def127) PvpLevel(def99) MaxHrsPerDay(def24) RunicName(def"runic coin")

Combat  (settings_combat_page_proc @0x41a260)
  AttackCmd(+0x519d def"kill") MultAttack(+0x51a8) PreAttack(+0x51b3) AttackSpl(+0x51be)
  BsWeapon/NrmWeapon/AltWeapon/Shield(+0x528a..0x52e7) UseShieldForBS UseNrmWeapForSpells
  CanBackStab DontBsIfMulti RunIfBsFails AttackNeutral PoliteAttacks AttackLast
  MaxMstrs MaxMstrExp RunRooms FleeRooms FleeTimeout RunBackwards BreakB4Running

Spells  (settings_spells_page_proc @0x42e3d0)
  ManaMultAtt ManaPreAtt ManaAttack(cast-floor%) MaxCastCnt PreCastCnt MultCastCnt MultMstrCnt
  MultMaxDmg PreMaxDmg AttMaxDmg BlessCmd1..10(+0x4ee3 stride0x14) ManaBless BlessResting
  BlessCombat LightCmd(+0x4ea4) LightDimRooms HpFullCmd(+0x4eb9) MaFullCmd(+0x4ece)

Health/Recovery  (settings_health_page_proc @0x42d0c0)
  HP:   HpFull HpRest HpHeal HpHealAtt HpRun HpLogoff HpHealPeriod
  Mana: ManaFull ManaRest ManaHeal ManaHealAtt ManaRun
  UseMeditate MeditateB4Rest PreRestCmd(+0x5009) PostRestCmd(+0x506e)
  HealCmd/RegenCmd/FluxCmd+FluxMin/BlindCmd/PoisonCmd/DiseaseCmd/FreedomCmd(+0x4e04..0x4e8f)
  IgnorePoison IgnoreBlind IgnoreConfusion
  (NB rest model = Min(trigger=*Rest) / Max(resume=*Full) PER HP and PER Mana — see combat_rest_decide
   @0x40b380. RESOLVED from the dialog control->offset map in settings_health_page_proc @0x42d0c0
   (declared order HpFull HpRest HpHeal HpHealAtt HpRun HpLogoff): HpFull=0x3758, HpRest=0x375c,
   HpHeal=0x3760, HpHealAtt=0x3764, **HpRun(wimpy/flee)=0x3768**, HpLogoff=0x376c; Mana mirrors at
   ManaFull=0x3774, ManaRest=0x3778, ManaHeal=0x377c, ManaHealAtt=0x3780, ManaRun=0x3784. So
   **0x3768 is HpRun (the flee threshold), NOT HpFull** — the earlier ambiguity is settled. The
   flee driver combat_flee_or_hide_decide @0x407f70 arms a RunRooms walk when hp < maxhp*HpRun/100;
   HpFull(0x3758)/ManaFull(0x3774) are the rest-resume targets.)

Events/AFK/PvP/Safety  (settings_events_page_proc @0x423270)
  AFK:   AutoAfk AutoAfkOff AfkMinimized AfkTimeout AfkReply CmdReply PopupAfkMsgs ShowAllAfk
         AlertWhenAfk Alert{Idle,Train,LowHPs,Hangup,PvP,Tele,Page,Talk,Gangpath,Gossip,Auction,
         Broadcast} DisableEvents EventsAfkOnly
  PvP:   PvpAction RedialPvp PvpSafePeriod PvpSpell1(+0x51c9) PvpSpell2(+0x521a) PvpFleeRoom(+0x3a78)
         LookPlayers GreetPlayers
  Remote:NoRemoteCmds WarnRemote Divert{Local,Tele,Gossip,Gang,Broad} LogTalk LogFile
  Safety:LogoffLowExp MinExpRate LagWait RelogInstead Hangup{NotAfk,AllOff,Naked,WhenAfk} DelPlayers
         ScrollMem AutoAutoCombat AutoAutoHeal

Navigation/Stealth  (folded into Combat/General pages)
  Nav:    CanPickLocks CanDisarmTraps BashMax PickMax DisarmMax SearchMax SearchNeedItem AutoMove
          AutoDoor SysGoto(+0x37b8) EntryCmd(+0x50d3) ExitCmd(+0x5138)
  Stealth:AutoSneak AutoHide MustSneak SuperStealth AutoTrack TrackEnemies TrackDelay HideDelay

Items/Cash
  WantCopper/Silver/Gold/Plat/Runic DontBeHeavy DontBeMedium GetAfterCombat DropCoins
  LimitWealth MinWealth MaxWealth LimitCoins MaxCoins Bank(+0x3250 def"Bank of Godfrey") AutoTrain
  InvLock + 14 per-slot equip locks (Weapon Shield Head Neck Back Torso Waist Arms Wrist Hands
  Finger1 Finger2 Legs Feet)

Party
  PartyRank AttLeaderMstr DefendParty ShareDamage ShareCash AskHealth HelpBash NoPartyCmds NoGangCmds
  IgnoreParty IgnoreWait IgnorePanic SendPanic NotifyGang PartyMaxMstrs PartyMaxExp
  PartyHeal1/2(+0x35c8/0x35dd) PartyAskHeal PartyWait PartyWaitMax ParPeriod
  PartyBless1..4(+0x4fb5)+PartyBlessWait1..4 PartyWaitCmd(+0x3723 def"wait") PartyResumeCmd(+0x3738)

Toolbar  (settings_toolbar_page_proc @0x492380)
  Auto{Combat,Nuke,Heal,Bless,Light,Cash,Get,Search,Sneak,Hide,Track} + two cmd slots each
  Def{...}{1,2} NoModeDefs ShowTools

Display  (settings_display_page_proc @0x45b4c0)
  Ansi/Talk fonts, BorderClr + color swatches, Show{Info,RunMsg,Rounds,Send,Talk,Who,Stat,Sess,Time,
  Rate,Party,Tools} Graph1000 GraphPeriod TalkTime TalkView UseTaskBar StartMinimized
  Confirm{Exit,Hangup,Settings,Delete} Sound AutoHideParty

Comms/Modem  (settings_comms_page_proc @0x410f20, settings_modem_page_proc @0x4116e0)  — LEGACY dial-up, N/A for telnet

Persisted UI state (restored, not "settings"): DataDir/ImportDir/CaptureDir/DownloadDir, SelPath/CurPath/
  CurPathStep/CurMap/FixSteps, all *WinPos, Minimized/Maximized, Sort* columns, LastEdit* cursors,
  NoHangup, BackupData.
```

**Ported to / mapped:** `src/mmud/config/schema.py` covers Combat/Spells/Items/Nav/Stealth well, partially
Health/Party/AFK/PvP. Gaps + the web/TUI exposure plan are in `docs/ROADMAP.md` §C. The main views' WndProcs:
`combat_stats_window @0x481620`, `party_window @0x4630e0`, `exp_graph_draw @0x42cb30`, `goto_location_dialog
@0x427890`, `path_editor_dialog @0x4661d0`.
