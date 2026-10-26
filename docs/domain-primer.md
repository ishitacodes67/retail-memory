# Domain primer

Notes for the retail-memory project. Written from my own understanding, not copied.

## Profit vs. revenue

Revenue is what customers pay you that is (price x units). 
whereas Profit is what stays after the costs that is ( price-cost) x units.

what happens to profit when you discount, and why a revenue increase can hide a profit loss?? 

When you put things on sale, you make less money on every item you sell, but your costs stay exactly the same. So even if a discount brings in a massive rush of customers and makes your total sales look huge, you can easily end up doing twice as much work for less total profit at the end of the day 

This is why "sales went up" is not a success metric. The right question is "did profit go up?"

## Price elasticity

Elasticity is a scoreboard showing how sensitive customers are to price. The number is almost always negative — price up, units down. A value of −2 means that for every 1% price cut, units rise by about 2%. So a 10% discount would give roughly 20% more units. Not from gut feeling — from estimated elasticity combined with margin. This project builds that estimate.

## Cannibalization

Cannibalization happens when a discount on one item doesn't bring in new shoppers, but instead steals customers away from your other full-priced products, shifting sales around without growing the business
It hides incredibly well because the sales boost on the discounted item is loud and obvious, while the drop in your other items is quiet and looks like normal noise

for example :- Discounting Brand X detergent by 25% causes its sales to shoot up by 40%, meanwhile causes the identical Brand Y detergent next to it to drop by 30%, leaving the store's total detergent sales completely flat.

## Baseline

The baseline is the exact number of sales you would have made if you had never run the promotion in the first place

Why "Before vs. During" is Wrong:- Comparing promo sales to last week's sales is a trap because it ignores outside factors; for instance, if you run a ice cream promo during a massive summer heatwave, sales would have spiked anyway even without the discount.

How to Estimate it Better:- A much better approach is using a control product—tracking a similar, non-promoted item during that exact same week to see how the market naturally behaved.

## Confounding

Confounding is when a hidden third factor takes credit for your success. Promotions are usually scheduled during high-demand periods — holidays, paydays, weekends. So sales look higher during promos, and you conclude the promo worked. But sales would have been high anyway because of the holiday. That's confounding: the "treatment" (promo) is tangled with another cause (holiday). One fix is a control group — compare against a nearby store that didn't run the promo that same weekend. If their sales also rose, the promo did nothing.