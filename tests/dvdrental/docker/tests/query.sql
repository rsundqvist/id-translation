SELECT customer_id,
       inventory.film_id,
       film_category.category_id,
       staff_id,
       rental_date,
       return_date
FROM rental
         LEFT JOIN inventory ON rental.inventory_id = inventory.inventory_id
         LEFT JOIN film_category on film_category.film_id = inventory.film_id
ORDER BY rental.rental_id DESC;
