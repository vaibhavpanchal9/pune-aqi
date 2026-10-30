# Data quality — 30 Oct 2026

Produced by `python quality_report.py` (default station: Panchawati_Pashan, 12238693). Every number
in the policies in `decisions.md` points at a table here. Re-run after any change to the ingest.

## Headline numbers
1. Pashan is missing 1,354 of 14,792 hours (9.2%). 685 of those hours (51%) sit in 8 holes of a day
   or more; 380 (28%) in 33 holes of 6–23 h; 87 in 25 holes of 3–5 h; 202 (15%) in 163 gaps of 1–2 h.
2. Exact zeros: 2,000+ across stations, 83 at Pashan (0.6%). They occur in flat runs of identical
   values (section D), i.e. a stuck instrument, not clean air. Negatives: 8, all at Park Street Wakad.
   Values ≥ 985 (instrument ceiling 1000): 5 in the whole table, none at Pashan.
3. Network-wide outages: 42 days with fewer than half of the possible readings, 15 of them with
   zero readings from any station: 9–10 Apr 2025, 11–19 Jan 2026, 24 Jun 2026, 24–26 Oct 2026.

## A. Gap lengths at Pashan
    bucket             n_gaps  hours_missing
    -----------------  ------  -------------
    1  no gap          13257   0
    2  1-2 h missing   163     202
    3  3-5 h missing   25      87
    4  6-23 h missing  33      380
    5  a day or more   8       685



## B. Missing hours per month at Pashan
month    grid_hours  present  missing  pct_missing
-------  ----------  -------  -------  -----------
2025-02  245         245      0        0.0        
2025-03  744         709      35       4.7        
2025-04  720         517      203      28.2       
2025-05  744         662      82       11.0       
2025-06  720         665      55       7.6        
2025-07  744         713      31       4.2        
2025-08  744         727      17       2.3        
2025-09  720         704      16       2.2        
2025-10  744         712      32       4.3        
2025-11  720         669      51       7.1        
2025-12  744         733      11       1.5        
2026-01  744         498      246      33.1       
2026-02  672         574      98       14.6       
2026-03  744         715      29       3.9        
2026-04  720         686      34       4.7        
2026-05  744         694      50       6.7        
2026-06  720         638      82       11.4       
2026-07  744         713      31       4.2        
2026-08  744         643      101      13.6       
2026-09  720         707      13       1.8        
2026-10  700         563      137      19.6       

Worst months: Jan 2026 33.1%, Apr 2025 28.2%, Oct 2026 19.6%, Feb 2026 14.6%, Aug 2026 13.6%.
All but one are network-wide events (section F); the rest of the months lose 1.5–11%.



## C. Impossible and suspicious values, per station
station                                        sensor_id  n      negative  zero  ceiling_985plus  spike_4x  dropout_4x
---------------------------------------------  ---------  -----  --------  ----  ---------------  --------  ----------
Bhosari, Pune - IITM                           12304615   10414  0         198   0                1         5         
Bhumkar Nagar, Pune - IITM                     12238676   11277  0         99    1                2         11        
Dhankawadi, Pune - IITM                        12238734   9434   0         98    1                0         6         
Gavalinagar, Pimpri Chinchwad - MPCB           12237987   11370  0         29    2                10        17        
Hadapsar, Pune - IITM                          12236449   8588   0         170   0                0         10        
Katraj Dairy, Pune - MPCB                      12248370   11593  0         101   1                6         6         
Mhada Colony, Pune - IITM                      12236443   12933  0         202   0                0         7         
Panchawati_Pashan, Pune - IITM                 12238693   13487  0         83    0                0         5         
Park Street Wakad, Pimpri Chinchwad - MPCB     12237996   12373  8         73    0                1         20        
Revenue Colony-Shivajinagar, Pune - IITM       12236463   12268  0         256   0                0         6         
Savitribai Phule Pune University, Pune - MPCB  12238005   8158   0         55    0                0         5         
Thergaon, Pimpri Chinchwad - MPCB              12243017   12648  0         20    0                16        23        
Transport Nagar-Nigdi, Pune - IITM             12236457   12199  0         527   0                1         11        

- Negative values exist only at Park Street Wakad (8).
- Zeros everywhere; Transport Nagar-Nigdi has 527, Revenue Colony 256, Mhada Colony 202. Pashan 83.
- Ceiling values (≥ 985): Gavalinagar 2, Bhumkar Nagar 1, Dhankawadi 1, Katraj 1.
- Spikes (> 4× both neighbours): Thergaon 16, Gavalinagar 10, Katraj 6; Pashan 0.
- Dropouts (< ¼ of both neighbours): Thergaon 23, Park Street 20, Gavalinagar 17; Pashan 5
  (one is 2026-02-03 07:30: 90.3 → 13.0 → 52.1).



## D. Stuck sensors (runs of 6+ identical consecutive values)

Hadapsar, Pune - IITM                          12236449   13               121          402                 10.6           
Transport Nagar-Nigdi, Pune - IITM             12236457   31               32           376                 0.0            
Dhankawadi, Pune - IITM                        12238734   26               31           338                 21.7           
Revenue Colony-Shivajinagar, Pune - IITM       12236463   9                191          258                 225.1          
Park Street Wakad, Pimpri Chinchwad - MPCB     12237996   20               51           232                 11.6           
Katraj Dairy, Pune - MPCB                      12248370   17               21           171                 12.5           
Mhada Colony, Pune - IITM                      12236443   11               23           149                 0.0            
Bhosari, Pune - IITM                           12304615   7                38           131                 0.0            
Panchawati_Pashan, Pune - IITM                 12238693   6                16           72                  0.0            
Bhumkar Nagar, Pune - IITM                     12238676   2                65           72                  0.0            
Thergaon, Pimpri Chinchwad - MPCB              12243017   2                23           29                  131.0          
Savitribai Phule Pune University, Pune - MPCB  12238005   2                17           23                  0.0            


- Revenue Colony-Shivajinagar: one run of 191 hours at 225.1 µg/m³ — eight days of a frozen high
  reading. Its station average (57.5, the highest) is partly this.
- Hadapsar: 402 hours in flat runs, longest 121 h at ~10.6. Nigdi: 376 hours, all at 0.0.
- Pashan: 6 runs, 72 hours, all at 0.0 — covered by the zero rule.

## E. Timestamp alignment

minute  n     
------  ------
30      146742

 — all 146,742 rows on minute 30 UTC (CPCB's IST hours). No off-grid readings.




## F. Network-wide outage days

day         readings  stations
----------  --------  --------
2025-04-09  0         0       
2025-04-10  0         0       
2025-04-11  110       10      
2025-04-14  103       11      
2025-04-15  151       13      
2025-05-25  125       11      
2025-05-26  121       10      
2025-05-28  143       11      
2025-06-03  147       11      
2025-06-29  149       10      
2025-07-21  146       7       
2025-09-08  155       9       
2025-10-26  79        11      
2025-11-03  122       10      
2026-01-10  92        10      
2026-01-11  0         0       
2026-01-12  0         0       
2026-01-13  0         0       
2026-01-14  0         0       
2026-01-15  0         0       
2026-01-16  0         0       
2026-01-17  0         0       
2026-01-18  0         0       
2026-01-19  0         0       
2026-01-20  100       11      
2026-02-03  89        12      
2026-02-08  82        10      
2026-02-16  42        11      
2026-02-17  105       11      
2026-02-18  154       11      
2026-05-05  143       13      
2026-06-23  62        13      
2026-06-24  0         0       
2026-06-25  104       12      
2026-08-27  99        11      
2026-08-28  77        11      
2026-08-29  11        11      
2026-10-18  141       11      
2026-10-24  0         0       
2026-10-25  0         0       
2026-10-26  0         0       
2026-10-30  43        12      

Episodes with zero readings from every station: 9–10 Apr 2025 · 11–19 Jan 2026 · 24 Jun 2026 ·
24–26 Oct 2026. Partial days (10–12 stations, under half the readings) cluster around each episode.
These cannot be fixed on our side; they are listed so the README's "where it loses" is honest.

## What Step 6 does with this
See `decisions.md`, entries dated 2026-10-30: the value policy (what becomes NULL) and the gap
policy (what gets filled, what gets excluded). Expected effect at Pashan: ~88 readings (0.65%)
become NULL; ~250 missing hours get forward-filled; ~1,100 hours stay missing and are excluded.