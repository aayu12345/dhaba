from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import db_helper
import logging
import generic_helper

app = FastAPI()
inprogress_orders={}

# Configure logging
logging.basicConfig(level=logging.INFO)

@app.post("/")
async def handle_request(request: Request):
    try:
        payload = await request.json()
        logging.info(f"Received payload: {payload}")

        intent = payload['queryResult']['intent']['displayName']
        parameters = payload['queryResult']['parameters']
        output_contexts = payload['queryResult']['outputContexts']
        session_id = generic_helper.extract_session_id(output_contexts[0]['name'])
        intent_handler_dict={

            'order.add - context: Ongoing-order':add_to_order,
            'Order.remove - context: Ongoing-order': remove_from_order,
            'order.complete - context: Ongoing-order':complete_order,
            'track.order - context: Ongoing-tracking':track_order,
            
        }
        return intent_handler_dict[intent](parameters,session_id)

        
    except Exception as e:
        logging.error(f"Error handling request: {e}")
        return JSONResponse(content={"fulfillmentText": "An error occurred"}, status_code=500)

#async def handle_request(request: Request):
        
        
    
 #       payload = await request.json()
  #      logging.info(f"Received payload: {payload}")

   #     intent = payload['queryResult']['intent']['displayName']
    #    parameters = payload['queryResult']['parameters']
     #   output_contexts = payload['queryResult']['outputContexts']

       # intent_handler_dict={
        #     'order.add - context: Ongoing-order':add_to_order,
            # 'Order.remove - context: Ongoing-order': remove_from_order,
             #'order.complete - context: Ongoing-order':complete_order,
         #    'track.order - context: Ongoing-tracking':track_order,
            
        #}
        #return intent_handler_dict[intent](parameters)

def add_to_order(parameters: dict, session_id: str):
    try:
        food_items = parameters["food-item"]
        quantities = parameters["number"]

        if len(food_items) != len(quantities):
            fulfillment_text = "Sorry, I didn't understand. Can you please specify both food items and their quantities?"
        else:
            new_food_dict = dict(zip(food_items, quantities))
            if session_id in inprogress_orders:
                current_food_dict = inprogress_orders[session_id]
                for food_item, quantity in new_food_dict.items():
                    if food_item in current_food_dict:
                        current_food_dict[food_item] += quantity
                    else:
                        current_food_dict[food_item] = quantity
                inprogress_orders[session_id] = current_food_dict
            else:
                inprogress_orders[session_id] = new_food_dict

            order_str = generic_helper.get_str_from_food_dict(inprogress_orders[session_id])
            fulfillment_text = f"So far you have: {order_str}. Do you need anything else? If you want to order more, say (add 2 pizza). If you're done, say (that's it or nope). If you want to remove an item, say (remove 1 pizza)."
        
        logging.info(f"Fulfillment text: {fulfillment_text}")
        return JSONResponse(content={"fulfillmentText": fulfillment_text})

    except Exception as e:
        logging.error(f"Error in add_to_order: {e}")
        return JSONResponse(content={"fulfillmentText": "An error occurred while adding the order"}, status_code=500)

def complete_order(parameters:dict , session_id:str):
    if session_id not in inprogress_orders:
        fulfillment_text= "I'm having some trouble to finding your order . Sorry! Can you place a new order"
    else:
        order=inprogress_orders[session_id] 
        order_id=save_to_db(order)

        if order_id==-1:
            filfillment_text="Sorry , I couldn't process your order due to backend error." \
                             " please place a new order again"

        else :
            order_total = db_helper.get_total_order_price(order_id)
            fulfillment_text = f"Awesome . We have placed your order. "\
                               f"Here is your order id # {order_id}."\
                               f"Your order total is {order_total} rupees.  which you can pay at the time of delivery!. For tracking your order give instructions like (track order) "
            
        del inprogress_orders[session_id]    
    return JSONResponse(content={
        "fulfillmentText": fulfillment_text
        })        
def save_to_db(order:dict):
    next_order_id = db_helper.get_next_order_id()

    for food_item , quantity in order.items():
        rcode = db_helper.insert_order_item(
            food_item,
            quantity,
            next_order_id
        )

        if rcode==-1:
            return -1
        
    db_helper.insert_order_tracking(next_order_id  , "in progress")    

    return next_order_id        
         



def track_order(parameters: dict , session_id:str):

    try:
        number = parameters['number'][0]  # Assuming 'number' is a list
        order_status = db_helper.get_order_status(number)

        if order_status:
            fulfillment_text = f"The order status for order_id: {number} is : {order_status}"
        else:
            fulfillment_text = f"No order found with order id: {number}"

        logging.info(f"Fulfillment text: {fulfillment_text}")
        return JSONResponse(content={"fulfillmentText": fulfillment_text})
    except Exception as e:
        logging.error(f"Error in track_order: {e}")
        return JSONResponse(content={"fulfillmentText": "An error occurred while tracking the order"}, status_code=500)

def remove_from_order(parameters: dict, session_id: str):
    if session_id not in inprogress_orders:
        return JSONResponse(content={
            "fulfillmentText": "I'm having trouble finding your order. Sorry! Can you place a new order, please?"
        })

    food_items = parameters.get("food-item", [])
    numbers = parameters.get("number", [])
    
    # Ensure food_items and numbers are lists of the same length
    if not isinstance(food_items, list):
        food_items = [food_items]
    if not isinstance(numbers, list):
        numbers = [numbers]

    if len(food_items) != len(numbers):
        return JSONResponse(content={
            "fulfillmentText": "There was an issue with your request. Please specify the items and their respective quantities correctly."
        })

    current_order = inprogress_orders[session_id]
    removed_items = []
    no_such_items = []

    for item, qty in zip(food_items, numbers):
        item_name = item
        quantity_to_remove = int(qty) if isinstance(qty, (int, float)) else 1

        if item_name not in current_order:
            no_such_items.append(item_name)
        else:
            current_quantity = current_order[item_name]

            if current_quantity <= quantity_to_remove:
                removed_items.append(f"{current_quantity} {item_name}(s)")
                del current_order[item_name]
            else:
                removed_items.append(f"{quantity_to_remove} {item_name}(s)")
                current_order[item_name] = current_quantity - quantity_to_remove

    fulfillment_texts = []

    if removed_items:
        fulfillment_texts.append(f'Removed {", ".join(removed_items)} from your order!')

    if no_such_items:
        fulfillment_texts.append(f'Your current order does not have {", ".join(no_such_items)}.')

    if not current_order:
        fulfillment_texts.append("Your order is now empty!")
    else:
        order_str = generic_helper.get_str_from_food_dict(current_order)
        fulfillment_texts.append(f"Here is what is left in your order: {order_str}. Do you need anything else?")

    return JSONResponse(content={
        "fulfillmentText": " ".join(fulfillment_texts)
    })



if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

