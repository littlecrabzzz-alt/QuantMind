# Bounded throughput review; no production changes

text_contracts used existing cloud-compose quantmind/worker business entry, SQLite mode=ro/query_only. Readonly task results retrieved by7knownCeleryIDs from completedlogs; no taskdispatch. SQLite statements have4s deadline; mainmetadata round0.0097s. Onlylast300attempts byrowid, matchingjobs byPK,40smallobservation envelopes, capability/gates smalltables and40planning-state summaries. EXPLAIN did not execute full discoveryquery. No upstream requests, configuration/weight/resource changes, pauses, publications or fulljob scans. Do not redo prior family14/Macfixed acceptance.

## Observed completed batches

Seven real acquire_only completions03:21:35–03:34:28Z: requests165,244,252,151,248,209,239; sum1508 over898.376s total tasktime =100.72requests/wall-minute. Acquire-stage total yields138.50requests/minute (account config240, batch360/90s). Planning25.63–29.10s each,191.60s total=21.33% totalwall. Initialization3.72–4.09s. One acquire110.31s exceeded nominal90s; code checks between synchronousrequests/reconciliation, not hardinterruption. These7cyclesdidnotpublish. Existing observedpublish-only about35.90s, configured900s cadence, consumes separatecontinuation; no evidence thatpublish explains these7acquisitioncycle losses. Logs were truncatedrepr, so exactmetrics came from read-only storedCelerytaskresults, not guessedlogcontent.

Last300attempt sample:201empty_unverified,88sample_ok,5possibly_truncated,4api_error,2schema_gap; allHTTP200; noobservedpermissiondenied orratelimit inthissample. Ofthesehistory163empty/50sample_ok/3saturated/3api_error; recent38empty/38sample_ok/2saturated/2schema_gap/1api_error.69of201emptiesexplicitlyrequest1990 dates, otheremptiesdistributedacrossyears/snapshots: broadscope andholidays/earlyavailability make requestcountdifferentfromusefulrowcount. Do not drop earlyscope ordeclare emptyascoverage.40mostrecentcapture requested_at→fetched_at spans median0.041s,total5.264s,max1.766s; includes HTTP andrawpersistence, not purewirelatency orcompletebatchbreakdown. No instrumentation currently separates gate sleep/network/decode/normalize/reconcile CPU duringacquire, so remainingacquiretime cannotbeassignedtosupplierwaiting.

## Rates and shares

Configaccount240rpm,onlyAPIoverridefund_portfolio240; api_min_interval hk_daily3605s. Actual quota:hk_daily persisted5/day gives17280sminimum plusexistingfuturegate (~61537sremaining atcapture); mustnotrelax. Endpoint effectiveceiling=min(configAPI(default200),contractrpm) thenaccountgate/maxexplicitinterval/observedquota. NewconfigAPI240alone cannotoverridecontract30.

20enabledAPI families eachweight1,rrgweight3,total23(documents separate). Sample300:rrg40,eachother20group13, matchingfairoutershares. Ataccount240 andallgroupsready, onefamilyabout10.43rpm; fiveAPItechnicalroundrobinabout2.09rpm/API. Thus current30rpmtechnicalcaps are notsupportedasdominantbottleneck; raising themwon'tnecessarilyimproveaggregate rate.

Savedofficialtechnicalcontracts/docs source review2026-09-09 (not freshwebvisit): stk_factor doc296 tiers5000points100rpm/8000points500rpm; stk_factor_pro doc3285000points30rpm/8000points500rpm; cyq_perf doc293 daily5000/10000/15000tiers20000/200000/unlimited withnoexplicitperminuterate; cyq_chips doc294 same dailytiers and200rpm; bak_daily doc255 no numericrate. Allfiveoperationalcontracts30rpm. docs/tushare-technical-extra-intake.md and TECHNICAL_EXTRA_CONTRACTS source_html_sha256/docURLs preserveprovenance.10100points doesnotproveexactcurrentaccountentitlements orunlistedAPIrate. Anypotentiallaterincrease mustuse documentedendpointtier/actualaccountqualification andobservedgates, notaccount240asAPIgrant.

## CPU/memory boundary

Measuredactualtushare-worker cgroup0.75CPU/1GiB, notquantmind'slargerbudget. Tworeadonlysamples~34.74s apart:CPUusage+16.90s,81/347periodsthrottled,+1.819sthrottled_usec; memory.current1053741056→859086848B; memory.events.max+7285,OOM/OOMkill0. Pressure/throttlingexists; cumulativecgroupcounters andoneintervaldonotquantifyhowmuchplanning/HTTPslownessitcaused. Resourcechangesaredeferredpendingbetterstageattribution, notpromisedacceleration.

## Exact code paths and minimal next candidate

- tick measureinitialize callsPipeline.initialize: seed/sourceindustryETF discovery plusfunds×years×quarters fullenqueue. Thisis~4sinitialize, NOT25–29splanning. Optimizeonlyafterseparatebenefitproof; preserveallhistoricalfunds/listdates/jobkeys/weeklyepochs.
- tick measureplanning callsplan_extended. Itfirstcallsidentifiers unconditionally. identifiersSQLUNIONselectsfullresultfromjobsandattempts:readonlyEXPLAINshowsSCANjobs,UNIONtemporaryBtree,SCANattempts. For eachresult,records readsentireimmutableJSON andbuildslistofdicts, includingwide technical/daily responses. UNIONofwholeobservationresultsdoesnotdeduplicateidenticalrawbody acrossdifferentobservations. Plausiblecostandmemorysource, notyetmeasuredstagefraction.
- Remainingplan_extended replaysoriginalgenerator withislice(offset) foreachfrozenfamily/mode, thenboundednewwork.40persistedstates sumoffset971723; maxtechnical94237,market66137; originaloffsetreplay isO(offset) andcooperativehistorytimecannotpreemptfirstnext. Countsare not equalCPUseconds, no causalwinnerclaimed.

Recommendedsmallcandidate firstaddplanning timing foridentifiers,perfamilyreplay/targetenqueue; keepmanifest/schema/queueidentity/signature untouched. Optionalwithin-call seenkey(api_name,object_sha256,status,response_format) inidentifiers avoidsreadingexactsameeligibleimmutablebodyrepeatedly; keepdifferentAPI/status/format separate, no cross-tickcache andnoobservationdeletion. Verify old/newidentifierlistsbyte-equal including retiredT/HKsuffix/ETFcash handling, samebodymultipleobservations, changedbody, errorevidencefollowedbyvalid, samebodydifferentAPI, andmissingfilesstillvisible. Syntheticduplicatebodybenchmark mustestablishbenefit; itcannotremove fullSQLscan. Largerincrementaldiscoverycursor/index orplannerseekrequiresseparatereviewandmigrationproof, notpartofthisread-onlytask.

Do not increaseRPM/weights ortrimhistory asfirstresponse. Fairconsumptionalreadyremovesstarvation; nexteffective-speedworkshouldmeasureandsuppressredundantdiscovery/replay whilepreservingcompletehistory andas-ofsourceobservations. AbsolutefinishETA cannotbe derivedfrom7batches: largeunknownscope,multiplefieldwidths,empties,attachmentsanddynamicdiscoveriesremain.

## Evidence hashes (files in /tmp)

- tushare-throughput-audit-live-20260909.json: b9d85ce16a7a0fc0ae315f26aff4909535e333f3f7ee8c01738cde168517428d
- tushare-throughput-task-meta-20260909.json: 66fcf6445c9799d8fbacd1781fb3889b6adb36c48cbb0cee075c5b80fa74a7a0
- tushare-throughput-completed-20260909.json: 5cd5ad86e84ba92d73d8667e6450f2dfbbb550ee8c583845cde68b7973a00de8
- tushare-throughput-worker-cgroup-before-20260909.json: f79916d6cf5398bbc7cac8aaf09432f9a1447a9d94f702e51150d6c1e68cb5ed
- tushare-throughput-worker-cgroup-after-20260909.json: dc1c4b7c263c0708ef8c62d2377fe0a7a2ba0f108043cb414ea5822ad06bec29
- tushare-planning-path-readonly-20260909.json: 9fae88a3f1eb5cdab9bb66b1e88e80fdb7835c6a9adfddb865da0527f6d23c8b
