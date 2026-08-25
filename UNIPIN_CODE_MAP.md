# UniPin Code Prefix → Product Mapping
> 10,704 লাইনের real API log বিশ্লেষণ করে তৈরি (4,048টি CALL entry)

## Code Format
```
BDMB-Q-S-15359391 2331-6265-6656-9336
└──────┘
 Prefix (এই অংশ দিয়ে product চেনা যায়)
```

## BDMB Series (Bangladesh Mobile)

| Prefix    | Product             | packageId |  Occurrences |
|-----------|---------------------|:---------:|:------------:|
| BDMB-T-S  | 25 Diamond          | 1         | 71           |
| BDMB-U-S  | 50 Diamond          | 2         | 60           |
| BDMB-J-S  | 115 Diamond         | 3         | 59           |
| BDMB-I-S  | 240 Diamond         | 4         | 138          |
| BDMB-K-S  | 610 Diamond         | 5         | 66           |
| BDMB-L-S  | 1240 Diamond        | 6         | 73           |
| BDMB-M-S  | 2530 Diamond        | 7         | 137          |
| BDMB-Q-S  | Weekly Membership   | 8         | 386          |
| BDMB-S-S  | Monthly Membership  | 9         | 471          |

## UPBD Series (UniPin Bangladesh)

| Prefix    | Product             | packageId |  Occurrences |
|-----------|---------------------|:---------:|:------------:|
| UPBD-Q-S  | 25 Diamond          | 1         | 112          |
| UPBD-R-S  | 50 Diamond          | 2         | 87           |
| UPBD-G-S  | 115 Diamond         | 3         | 132          |
| UPBD-F-S  | 240 Diamond         | 4         | 180          |
| UPBD-H-S  | 610 Diamond         | 5         | 80           |
| UPBD-I-S  | 1240 Diamond        | 6         | 52           |
| UPBD-J-S  | 2530 Diamond        | 7         | 167          |
| UPBD-N-S  | Weekly Membership   | 8         | 1126         |
| UPBD-P-S  | Monthly Membership  | 9         | 651          |

## Pattern Rule
- Format: `{SERIES}-{LETTER}-S-{serial} {pin}`
- **3য় segment সবসময় `S`** (fixed)
- **2য় segment (অক্ষর)** দিয়ে denomination বোঝা যায়
- `BDMB` = Bangladesh Mobile series
- `UPBD` = UniPin Bangladesh series
- দুটো series একই product দেয়, শুধু voucher batch আলাদা

## UniPin path_id
| Series  | path_id |
|---------|---------|
| BDMB-*  | 659     |
| UPBD-*  | 670     |
| অন্যান্য | 670    |
