
"""
From [x1,y2] and [x2,y2] compute dy|dx and next -->
Steps: until x1<x2 do:
	1) print point [x,round(y)]
	2) x = x+1
	3) y = y+(dy|dx)
"""

from matplotlib import pyplot

def plot_dda(x1, y1, x2, y2): # funcion

	# find absolute differences 
	dx = abs(x1 - x2)
	dy = abs(y1 - y2)

	num=max(dx,dy) # number of coordinates between two points

	# calculate the increment in x and y 
	xi = 1     # 1 pixel
	yi = dy/dx

	# start with 1st point 
	x = float(x1)
	y = float(y1)

	# make a list for coordinates 
	x_coorinates = [] 
	y_coorinates = [] 
    
	for i in range(num):
		# append the x,y lists with coordinates
		x_coorinates.append(x) 
		y_coorinates.append(y) 

		# increment the coordiantes
		x = x + xi
		y = y + yi

	# plot line
	pyplot.title("DDA algorythm")
	pyplot.plot(x_coorinates, y_coorinates, marker="x",
			markersize=6, markerfacecolor="blue")
	pyplot.show()


	# Function call here you can set your coordinates
plot_dda(1, 1, 12, 6)

