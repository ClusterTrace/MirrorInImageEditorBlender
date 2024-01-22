# Mirror For 2D Texturing Addon
# Author: ClusterTrace

# Instructions:
# 1. Run script or download addon
# 2. Have the 3D Viewport and Image Editor windows open
# 3. Look for the mirror tab on the right panel of the image editor window
# 4. Ensure wanted texture is selected in the image editor window
# 5. With the wanted object selected, and not in edit mode, in the panel press the snapshot button. This takes a snapshot of the texture and adds the required geonodes
# 6. Once snapshoted edit the texture in preferred method (likely through the image editor or the texture editing mode on the object) to either use the changes as a mask for what to mirror ("Mirror Changes As Mask" button) or to mirror the changes made ("Mirror Changes" button)
# 7. Ensure the wanted world axis for the mirror is selected using the x, y, or z buttons
# 8. Press "Mirror Changes" or "Mirror Changes As Mask" button depending on wanted effect
# 9. Optional: One axis can have its mirroring translations stored using the "Create Mapping" button with the wanted axis currently selected. This drastically speeds up mirroring, at the cost of a big upfront load. Only one mapping is stored at a time.

bl_info = {
    "name": "Mirrors Texture Changes",
    "blender": (4,0,0),
    "category": "Texture",
}

import bpy
import mathutils
import math
import time
import copy
import numpy as np


# To Do:
#- See if can improve how variables are stored
#- See if can speed up performace (geonode is slow and random delays at beginning (might be snapshotting), also try adding multithreading/gpu acceleration (maybe use CuPY)
#- Look into using models for operators to create tools for image editor
#- make option so the changes made are done via copying the changes (with limits to prevent going out of bounds for colors). This should help fix issues at mirror points. Or make it so it doesn't mirror if pixels are on the wrong side of the character (like only mirror left side of character by checking the mirror location of the point on the model, then comparing it with what side is suposed to be changing)
#- Can make it so mirrored changes are added to the mirror map (allows slowly adding to the mirror map, but would require checking if the map supported those pixels)
#- look into making a loading bar and having blender not freeze up when mirroring large chunks or making the map

#Known issues:
#- drawing over the mirror axis line or drawing on both sides of the mirror can cause drawing that is likely unwanted
#- 3D mirror sometimes has small pixel gaps caused by the point acquired from geometry nodes getting stuck on edges, as they stick outward more, or it is failing to read the corresponding pixel values for edges. Bandade fix is use a subdivision modifier before the geonodes so more face area exists or use Pixel Gap Fill
#- 2D mirroring will create small pixel gaps when mirroring on angles that are not multiples of 45 degrees. Bandade fix is to use Pixel Gap Fill
#- Addon has no way of telling if object it is using as a reference has had its geometry altered in between snapshot and mirror, which can cause undesired effects.
#- Geometry nodes and scripts likely run on cpu, which means expensive parallel computations like UV maps are far slower than they are supposed to be. Can't run cpu in parallel properly apparently in Blender (only runs one thread at a time)
#- Likely Doesn't work if there are overlapping UVs

def addSamplePointOnUVFromModelModifier(object):
    modifier = object.modifiers.new("SamplePointOnUVFromModel", "NODES") # adds the geometry node modifier to the object
    node_tree = bpy.data.node_groups.new("SamplePointOnUVFromModel", "GeometryNodeTree") # creates a blank geo node tree
    modifier.node_group = node_tree # adds the node tree to the geo node modifier

    # adds the input and output node
    inputNode = node_tree.nodes.new(type="NodeGroupInput")
    outputNode = node_tree.nodes.new(type="NodeGroupOutput")
    # adds sockets to input and output nodes (edits the geometry group/tree interface)
    node_tree.interface.new_socket(name='Geometry', in_out='INPUT', socket_type='NodeSocketGeometry')
    node_tree.interface.new_socket(name='Geometry', in_out='OUTPUT', socket_type='NodeSocketGeometry')
    #links input and output node
    #node_tree.links.new(inputNode.outputs["Geometry"], outputNode.inputs["Geometry"])

    #Adds required nodes
    vectorNode = node_tree.nodes.new(type="FunctionNodeInputVector")
    positionNode1 = node_tree.nodes.new(type="GeometryNodeInputPosition")
    sampleNearestSurfaceNode1 = node_tree.nodes.new(type="GeometryNodeSampleNearestSurface")
    sampleNearestSurfaceNode1.data_type = 'FLOAT_VECTOR' # updates data type for sampleNearestSurfaceNode
    pointsNode = node_tree.nodes.new(type="GeometryNodePoints")

    positionNode2 = node_tree.nodes.new(type="GeometryNodeInputPosition")
    sampleNearestSurfaceNode2 = node_tree.nodes.new(type="GeometryNodeSampleNearestSurface")
    sampleNearestSurfaceNode2.data_type = 'FLOAT_VECTOR' # updates data type for sampleNearestSurfaceNode

    namedAttributeNode = node_tree.nodes.new(type="GeometryNodeInputNamedAttribute")
    namedAttributeNode.data_type = 'FLOAT_VECTOR'
    namedAttributeNode.inputs[0].default_value = "UVMap"
    #splitEdgesNode = node_tree.nodes.new(type="GeometryNodeSplitEdges")
    #setPositionNode1 = node_tree.nodes.new(type="GeometryNodeSetPosition")
    #positionNode3 = node_tree.nodes.new(type="GeometryNodeInputPosition")
    #captureAttributeNode1 = node_tree.nodes.new(type="GeometryNodeCaptureAttribute")
    #captureAttributeNode1.data_type = 'FLOAT_VECTOR'

    setPositionNode2 = node_tree.nodes.new(type="GeometryNodeSetPosition")
    positionNode4 = node_tree.nodes.new(type="GeometryNodeInputPosition")
    captureAttributeNode2 = node_tree.nodes.new(type="GeometryNodeCaptureAttribute")
    captureAttributeNode2.data_type = 'FLOAT_VECTOR'
    attributeStatisticNode = node_tree.nodes.new(type="GeometryNodeAttributeStatistic")
    attributeStatisticNode.data_type = 'FLOAT_VECTOR'
    storedNamedAttributeNode = node_tree.nodes.new(type="GeometryNodeStoreNamedAttribute")
    storedNamedAttributeNode.data_type = 'FLOAT_VECTOR'
    storedNamedAttributeNode.inputs[2].default_value = "PointOnUV"

    # Links required nodes
    node_tree.links.new(inputNode.outputs["Geometry"], sampleNearestSurfaceNode1.inputs["Mesh"])
    node_tree.links.new(vectorNode.outputs["Vector"], sampleNearestSurfaceNode1.inputs["Sample Position"])
    node_tree.links.new(positionNode1.outputs["Position"], sampleNearestSurfaceNode1.inputs["Value"])
    node_tree.links.new(sampleNearestSurfaceNode1.outputs["Value"], pointsNode.inputs["Position"])
    node_tree.links.new(pointsNode.outputs["Geometry"], setPositionNode2.inputs["Geometry"])
    node_tree.links.new(inputNode.outputs["Geometry"], storedNamedAttributeNode.inputs["Geometry"])

    node_tree.links.new(inputNode.outputs["Geometry"], sampleNearestSurfaceNode2.inputs["Mesh"])
    node_tree.links.new(positionNode2.outputs["Position"], sampleNearestSurfaceNode2.inputs["Sample Position"])
    node_tree.links.new(sampleNearestSurfaceNode2.outputs["Value"], setPositionNode2.inputs["Position"])

    #node_tree.links.new(inputNode.outputs["Geometry"], splitEdgesNode.inputs["Mesh"])
    #node_tree.links.new(namedAttributeNode.outputs["Attribute"], setPositionNode1.inputs["Position"])
    #node_tree.links.new(splitEdgesNode.outputs["Mesh"], setPositionNode1.inputs["Geometry"])
    #node_tree.links.new(positionNode3.outputs["Position"], captureAttributeNode1.inputs["Value"])
    #node_tree.links.new(setPositionNode1.outputs["Geometry"], captureAttributeNode1.inputs["Geometry"])
    node_tree.links.new(namedAttributeNode.outputs["Attribute"], sampleNearestSurfaceNode2.inputs["Value"])

    node_tree.links.new(setPositionNode2.outputs["Geometry"], captureAttributeNode2.inputs["Geometry"])
    node_tree.links.new(positionNode4.outputs["Position"], captureAttributeNode2.inputs["Value"])
    node_tree.links.new(captureAttributeNode2.outputs["Geometry"], attributeStatisticNode.inputs["Geometry"])
    node_tree.links.new(captureAttributeNode2.outputs["Attribute"], attributeStatisticNode.inputs["Attribute"])
    node_tree.links.new(attributeStatisticNode.outputs["Mean"], storedNamedAttributeNode.inputs["Value"])
    node_tree.links.new(storedNamedAttributeNode.outputs["Geometry"], outputNode.inputs["Geometry"])


    # Fix node positions for readability
    inputNode.location = (0, 0)
    outputNode.location = (2000, 0)
    vectorNode.location = (0, 200)
    positionNode1.location = (200, 200)
    sampleNearestSurfaceNode1.location = (400, 200)
    pointsNode.location = (600, 200)
    positionNode2.location = (400, 0)
    sampleNearestSurfaceNode2.location = (600, 0)
    namedAttributeNode.location = (100, -600)
    #splitEdgesNode.location = (300, -400)
    #setPositionNode1.location = (500, -400)
    #positionNode3.location = (700, -500)
    #captureAttributeNode1.location = (900, -400)
    setPositionNode2.location = (800, 0)
    positionNode4.location = (1000, -100)
    captureAttributeNode2.location = (1200, 0)
    attributeStatisticNode.location = (1400, 0)
    storedNamedAttributeNode.location = (1600, 0)
    
    return modifier
    
def addSamplePointOnModelFromUVModifier(object):
    modifier = object.modifiers.new("SamplePointOnModelFromUV", "NODES") # adds the geometry node modifier to the object
    node_tree = bpy.data.node_groups.new("SamplePointOnModelFromUV", "GeometryNodeTree") # creates a blank geo node tree
    modifier.node_group = node_tree # adds the node tree to the geo node modifier

    # adds the input and output node
    inputNode = node_tree.nodes.new(type="NodeGroupInput")
    outputNode = node_tree.nodes.new(type="NodeGroupOutput")
    # adds sockets to input and output nodes (edits the geometry group/tree interface)
    node_tree.interface.new_socket(name='Geometry', in_out='INPUT', socket_type='NodeSocketGeometry')
    node_tree.interface.new_socket(name='Geometry', in_out='OUTPUT', socket_type='NodeSocketGeometry')
    #links input and output node
    #node_tree.links.new(inputNode.outputs["Geometry"], outputNode.inputs["Geometry"])

    #Adds required nodes
    vectorNode = node_tree.nodes.new(type="FunctionNodeInputVector")
    pointsNode = node_tree.nodes.new(type="GeometryNodePoints")

    positionNode2 = node_tree.nodes.new(type="GeometryNodeInputPosition")
    sampleNearestSurfaceNode2 = node_tree.nodes.new(type="GeometryNodeSampleNearestSurface")
    sampleNearestSurfaceNode2.data_type = 'FLOAT_VECTOR' # updates data type for sampleNearestSurfaceNode

    namedAttributeNode = node_tree.nodes.new(type="GeometryNodeInputNamedAttribute")
    namedAttributeNode.data_type = 'FLOAT_VECTOR'
    namedAttributeNode.inputs[0].default_value = "UVMap"
    splitEdgesNode = node_tree.nodes.new(type="GeometryNodeSplitEdges")
    setPositionNode1 = node_tree.nodes.new(type="GeometryNodeSetPosition")
    positionNode3 = node_tree.nodes.new(type="GeometryNodeInputPosition")
    captureAttributeNode1 = node_tree.nodes.new(type="GeometryNodeCaptureAttribute")
    captureAttributeNode1.data_type = 'FLOAT_VECTOR'

    setPositionNode2 = node_tree.nodes.new(type="GeometryNodeSetPosition")
    positionNode4 = node_tree.nodes.new(type="GeometryNodeInputPosition")
    captureAttributeNode2 = node_tree.nodes.new(type="GeometryNodeCaptureAttribute")
    captureAttributeNode2.data_type = 'FLOAT_VECTOR'
    attributeStatisticNode = node_tree.nodes.new(type="GeometryNodeAttributeStatistic")
    attributeStatisticNode.data_type = 'FLOAT_VECTOR'
    storedNamedAttributeNode = node_tree.nodes.new(type="GeometryNodeStoreNamedAttribute")
    storedNamedAttributeNode.data_type = 'FLOAT_VECTOR'
    storedNamedAttributeNode.inputs[2].default_value = "PointOnModel"

    # Links required nodes
    node_tree.links.new(inputNode.outputs["Geometry"], storedNamedAttributeNode.inputs["Geometry"])
    
    node_tree.links.new(vectorNode.outputs["Vector"], pointsNode.inputs["Position"])
    node_tree.links.new(pointsNode.outputs["Geometry"], setPositionNode2.inputs["Geometry"])

    node_tree.links.new(positionNode2.outputs["Position"], sampleNearestSurfaceNode2.inputs["Sample Position"])
    node_tree.links.new(sampleNearestSurfaceNode2.outputs["Value"], setPositionNode2.inputs["Position"])

    node_tree.links.new(inputNode.outputs["Geometry"], captureAttributeNode1.inputs["Geometry"])
    node_tree.links.new(captureAttributeNode1.outputs["Geometry"], splitEdgesNode.inputs["Mesh"])
    node_tree.links.new(captureAttributeNode1.outputs["Attribute"], sampleNearestSurfaceNode2.inputs["Value"])
    node_tree.links.new(namedAttributeNode.outputs["Attribute"], setPositionNode1.inputs["Position"])
    node_tree.links.new(splitEdgesNode.outputs["Mesh"], setPositionNode1.inputs["Geometry"])
    node_tree.links.new(positionNode3.outputs["Position"], captureAttributeNode1.inputs["Value"])
    node_tree.links.new(setPositionNode1.outputs["Geometry"], sampleNearestSurfaceNode2.inputs["Mesh"])

    node_tree.links.new(setPositionNode2.outputs["Geometry"], captureAttributeNode2.inputs["Geometry"])
    node_tree.links.new(positionNode4.outputs["Position"], captureAttributeNode2.inputs["Value"])
    node_tree.links.new(captureAttributeNode2.outputs["Geometry"], attributeStatisticNode.inputs["Geometry"])
    node_tree.links.new(captureAttributeNode2.outputs["Attribute"], attributeStatisticNode.inputs["Attribute"])
    node_tree.links.new(attributeStatisticNode.outputs["Mean"], storedNamedAttributeNode.inputs["Value"])
    node_tree.links.new(storedNamedAttributeNode.outputs["Geometry"], outputNode.inputs["Geometry"])


    # Fix node positions for readability
    inputNode.location = (0, 0)
    outputNode.location = (2000, 0)
    vectorNode.location = (0, 200)
    pointsNode.location = (600, 200)
    positionNode2.location = (400, 0)
    sampleNearestSurfaceNode2.location = (600, 0)
    namedAttributeNode.location = (100, -600)
    splitEdgesNode.location = (300, -400)
    setPositionNode1.location = (500, -400)
    positionNode3.location = (-100, -500)
    captureAttributeNode1.location = (100, -400)
    setPositionNode2.location = (800, 0)
    positionNode4.location = (1000, -100)
    captureAttributeNode2.location = (1200, 0)
    attributeStatisticNode.location = (1400, 0)
    storedNamedAttributeNode.location = (1600, 0)
    
    return modifier

#def validModifier(modifier, snapshotObject, selectedObject):
#    if (modifier != None): # if it isn't None
#        if (snapshotObject == selectedObject):# ensures the snapshot object matches currently selected object
#            try: # if it isn't an invalid pointer
#                modifier.items()
#                return True
#            except:
#                return False
#        else:
#            return False
#    else:
#        return False

# Inputs: ---------------------------
# modifier is a pointer to the modifier attached to an object
# snapshotObject is the pointer to the object the snapshot was taken on
# selectedObject is the currently selected object in the panel
def validModifier(modifier, snapshotObject, selectedObject):
    if (snapshotObject == selectedObject):
        # check if modifier is on object by iterating over its modifiers
        for i in snapshotObject.modifiers:
            if (i == modifier):
                return True
        return False

class textureSnapshot():
    
    # Inputs: ---------------------
    # texture is an image texture
    # pixels is a vector
    # sizeX is the x size of the texture
    # sizeY is the y size of the texture
    def __init__(self, texture = None, pixels = mathutils.Vector(), sizeX = 0, sizeY = 0):
        if (texture == None):
            self.pixels = pixels # a vector of the pixels
            self.sizeX = sizeX # an int of the x size
            self.sizeY = sizeY # an int of the y size
        else:
            self.pixels = mathutils.Vector(texture.pixels)
            self.sizeX = texture.size[0]
            self.sizeY = texture.size[1]
    
    # Input: ---------------
    # snapShot1 is the first texture snapshot TYPE: textureSnapshot
    # snapShot2 is the second texture snapshot TYPE: textureSnapshot
    # Purpose: -------------
    # returns the changes between the first and second texture
    def snapshotDifference(self, snapShot2):
        tempDiff = []
        # checks compatibility by size
        if (self.sizeX == snapShot2.sizeX and self.sizeY == snapShot2.sizeY):
            tempDiff = self.pixels - snapShot2.pixels
            return  tempDiff # returns difference between pixels
        else:
            print("Error: sizes of textures do not match")
            return [0]# return a pixel array for texture2's size that is all zeros

# Converts a pixel cordinate ((x, y) position) to the number it would be in a 1 dimensional list/array
# Assumes pixelNum is not made up of pixels split into 4 parts in a sequence, so multiply this by 4 to get the start of a pixel sequence
def pixelCordToPixelNum(pixelCord = [0, 0], sizeX = 0, sizeY = 0):
    return pixelCord[0] + pixelCord[1] * sizeX

# converts a pixelNum (the position of a piece of a pixel in a 1 dimensional array of pixels) to the cordinate of if it was a 2D array of pixels that are an array of 4 values (ex. (0, 0, 0, 0))
# this means multiply pixelNum by 4 if it is the beginning of a pixel sequance (the four values that make up the RGBA of the pixel)
def pixelNumToPixelCord(pixelNum = 0, sizeX = 0, sizeY = 0):
    displace = 4 # used to correct for every 4 pixel values corresponding to one real pixel's RGBA
    pixelCordinate = [0, 0]
    pixelCordinate[0] = math.floor(pixelNum / displace) % sizeX
    pixelCordinate[1] = math.floor((pixelNum / displace) / sizeX)
    return pixelCordinate

# Inputs: -------------
# uvCord is the 3D vector for the UV cordinate (ex. [0.5, 0.7])
# sizeX is the x size of the texture
# sizeY is the y size of the texture
# Purpose: ---------------
# This function converts a uv cordinate to a pixel cordinate then returns it
# Defaults to return 0, 0 if given bad input
def uvToPixel(uvCord = [0, 0], sizeX = 0, sizeY = 0):
    if uvCord != None:
        return [round(uvCord[0] * (sizeX - 1)), round(uvCord[1] * (sizeY - 1))]

# pixelNum is the total number of pixelValues in the texture (this is likely 4x the number of pixels in the texture)
def pixelToUV(pixelNum = 0, sizeX = 0, sizeY = 0):
    temp = pixelCordinateToUV(pixelNumToPixelCord(pixelNum = pixelNum, sizeX = sizeX, sizeY = sizeY), sizeX, sizeY)
    return temp
    
def pixelCordinateToUV(pixelCordinate = [0, 0], sizeX = 0, sizeY = 0):
    return [pixelCordinate[0] / sizeX, pixelCordinate[1] / sizeY]

# Inputs: ---------------
# snapshot is a textureSnapshot
# pixelLoc is the cordinate of the target pixel to update as a list of x,y cordinates (ex. [4, 2])
# pixelValue is the wanted value in the target pixel as a tuple (ex. (1, 1, 1, 1))
# Purpose: -----------------
# This function updates the pixel of a texture
def updatePixel(snapshot, pixelLoc, pixelValue):
    # might need to add a check as to whether there is an alpha
    displace = 4
    sizeX = snapshot.sizeX
    sizeY = snapshot.sizeY
    pixels = snapshot.pixels
    
    tempLoc = pixelLoc[0] + sizeX * pixelLoc[1]
    pixels[tempLoc * displace: tempLoc * displace + displace] = pixelValue

# This function requires the selected object has the required modifiers added to work
# Inputs: --------------
# object is the scene object used as the model the point is on
# point is a 3D vector representing the spot on the model (ex. [0, 1, 0])
# uv is a string of the name of the UV map for the object
# localSpace is whether the point is in local space
def getUVFromPointOnModel(object, point, uv, localSpace = True):
    tempPoint = point
    if (localSpace == False): # makes local
        tempPoint = tempPoint - object.location
    bpy.types.Scene.snapshotObjectModifierPointUV.node_group.nodes["Vector"].vector = tempPoint
    bpy.types.Scene.snapshotObjectModifierPointUV.node_group.nodes["Named Attribute"].inputs[0].default_value = uv
    objData = object.evaluated_get(bpy.context.evaluated_depsgraph_get()).data # grabs data
    tempUV = objData.attributes['PointOnUV'].data[0].vector # reads value
    
    uv = [tempUV[0], tempUV[1]]
    return uv

# Inputs: --------------
# object is the scene object used as the model the point is on
# point is a 2D vector representing the spot on the UV (ex. [0, 1])
# uv is a string of the name of the UV map for the object
# localSpace is whether the returned point is in local space
# Purpose: ------------------
# This retrieves the 3D vector of a point on a 3D model from a UV cordinate via the required geometry node
def getPointFromUV(object, point, uv, localSpace = True):
    bpy.types.Scene.snapshotObjectModifierPointModel.node_group.nodes["Vector"].vector[0] = point[0]
    bpy.types.Scene.snapshotObjectModifierPointModel.node_group.nodes["Vector"].vector[1] = point[1]
    bpy.types.Scene.snapshotObjectModifierPointModel.node_group.nodes["Named Attribute"].inputs[0].default_value = uv
    objData = object.evaluated_get(bpy.context.evaluated_depsgraph_get()).data # grabs data
    temp = objData.attributes['PointOnModel'].data[0].vector # reads value
    if localSpace == False:
        temp = temp + object.location
    return temp

# Inputs: --------------
# diff is the difference of the before mirror snapshot and the one after mirroring)
# snapshot is the textureSnapshot that is being edited (one after mirroring)
# threshold is an integer for how many adjacent pixels must be different in the snapshot to require blending (averaging the pixels value to nearby ones)
# selfBlend is a boolean for whether the unchanged pixel should factor in its own value to the blend
# This function takes the diff (the difference between snapshots made in things like the mirror functions) and the new snapshot to be able to try and guess which pixels need to be filled in to fix random gaps made in mirroring
def pixelGapFill(diff, snapshot, threshold=6, selfBlend=False):
    displace = 4
    pixelsToCheck = [] # list of pixels to check if needed to blend
    length = math.floor(len(diff) / displace)
    for i in range(length):
        if diff[i * displace: i * displace + displace] == (0, 0, 0, 0): # if there isn't change in a pixel
            pixelsToCheck.append(i)
    # check through the list of pixels to see how many of the pixels bordering it are changed
    length2 = len(pixelsToCheck)
    print("PixelsToCheck: " + str(length2)) # TIME
    for i in range(length2):
        changedPixels = []
        currentPixel = pixelNumToPixelCord(pixelsToCheck[i] * displace, snapshot.sizeX, snapshot.sizeY)
        topLeft = pixelCordToPixelNum([currentPixel[0] - 1, currentPixel[1] + 1], snapshot.sizeX, snapshot.sizeY)
        top = pixelCordToPixelNum([currentPixel[0], currentPixel[1] + 1], snapshot.sizeX, snapshot.sizeY)
        topRight = pixelCordToPixelNum([currentPixel[0] + 1, currentPixel[1] + 1], snapshot.sizeX, snapshot.sizeY)
        left = pixelCordToPixelNum([currentPixel[0] - 1, currentPixel[1]], snapshot.sizeX, snapshot.sizeY)
        right = pixelCordToPixelNum([currentPixel[0] + 1, currentPixel[1]], snapshot.sizeX, snapshot.sizeY)
        bottomLeft = pixelCordToPixelNum([currentPixel[0] - 1, currentPixel[1] - 1], snapshot.sizeX, snapshot.sizeY)
        bottom = pixelCordToPixelNum([currentPixel[0], currentPixel[1] - 1], snapshot.sizeX, snapshot.sizeY)
        bottomRight = pixelCordToPixelNum([currentPixel[0] + 1, currentPixel[1] - 1], snapshot.sizeX, snapshot.sizeY)
        if ((currentPixel[0] - 1) > 0 and (currentPixel[1] + 1) < snapshot.sizeY): # check if pixel is possible (topleft)
            if diff[topLeft * displace: topLeft * displace + displace] != (0, 0, 0, 0): # if the pixel is changed, add it to the list
                changedPixels.append(topLeft)
        if ((currentPixel[1] + 1) < snapshot.sizeY): # check if pixel is possible (top)
            if diff[top * displace: top * displace + displace] != (0, 0, 0, 0):
                changedPixels.append(top)
        if ((currentPixel[0] + 1) < snapshot.sizeX and (currentPixel[1] + 1) < snapshot.sizeY): # check if pixel is possible (topRight)
            if diff[topRight * displace: topRight * displace + displace] != (0, 0, 0, 0):
                changedPixels.append(topRight)
        if ((currentPixel[0] - 1) > 0): # check if pixel is possible (left)
            if diff[left * displace: left * displace + displace] != (0, 0, 0, 0):
                changedPixels.append(left)
        if ((currentPixel[0] + 1) < snapshot.sizeX): # check if pixel is possible (right)
            if diff[right * displace: right * displace + displace] != (0, 0, 0, 0):
                changedPixels.append(right)
        if ((currentPixel[0] - 1) > 0 and (currentPixel[1] - 1) > 0): # check if pixel is possible (bottomleft)
            if diff[bottomLeft * displace: bottomLeft * displace + displace] != (0, 0, 0, 0):
                changedPixels.append(bottomLeft)
        if ((currentPixel[1] - 1) > 0): # check if pixel is possible (bottom)
            if diff[bottom * displace: bottom * displace + displace] != (0, 0, 0, 0):
                changedPixels.append(bottom)
        if ((currentPixel[0] + 1) < snapshot.sizeX and (currentPixel[1] - 1) > 0): # check if pixel is possible (bottomRight)
            if diff[bottomRight * displace: bottomRight * displace + displace] != (0, 0, 0, 0):
                changedPixels.append(bottomRight)
        # if enough pixels are changed, then update the pixel to be a mix of its changed neighbors
        if (len(changedPixels) >= threshold):
            newValue = np.array([0, 0, 0, 0])
            for j in range(len(changedPixels)): # builds the value for the pixel using its neighbors
                tempNum = np.array(snapshot.pixels[changedPixels[j] * displace: changedPixels[j] * displace + displace])
                newValue = newValue + tempNum
            if (selfBlend): # factors itself into the blending
                newValue = newValue + np.array(snapshot.pixels[pixelsToCheck[i] * displace: pixelsToCheck[i] * displace + displace])
                newValue = newValue / (len(changedPixels) + 1)
            else:
                newValue = newValue / len(changedPixels)
            updatePixel(snapshot, currentPixel, newValue) # updates pixel in snapshot
    return snapshot # returns the snapshot it was given to edit


# Inputs: ------------
# object is an object from the scene
# point is a 3D vector of a location in the scene
# axis is a character, expected to be x, y, or z
# Purpose: ---------
# Mirrors the given point across the given world axis based on the objects origin, but defaults to returning given point if errored axis
def mirror3dCordinate(object, point, axis):
    tempPoint = mathutils.Vector(point)
    if axis == 'x':
        tempPoint[0] = tempPoint[0] * -1
    elif axis == 'y':
        tempPoint[1] = tempPoint[1] * -1
    elif axis == 'z':
        tempPoint[2] = tempPoint[2] * -1
    else:
        print("Error: axis input not valid")
        return point
    return tempPoint

# Inputs: ------------
# snapshot1 is a textureSnapshot
# snapshot2 is a textureSnapshot, expected to be of the same image dimensions of snapshot1
# object is an object from the scene
# texture is a image texture
# axis is a character, expected to be x, y, or z
# uv is the string for the name of the UV map used
# mask is a boolean for whether the changes are used as a mask or not
# pixelMap is a 2D list or array of how the pixels are mapped to their mirror (stores the mirror cordinate)
# pixelMapAxis is the axis the mirror cordinates used in the pixelMap (Ex. 'x', 'y', or 'z')
# Purpose: ---------
# This function performs the changes or the mirroring of information from the snapshots
def mirrorChangesFromSnapshots(snapshot1, snapshot2, object, texture, axis, uv = "UVMap", mask = False, pixelMap = None, pixelMapAxis = None, pixelGapFillBool=False, threshold=6, selfBlend=False):
    displace = 4
    if (bpy.types.Scene.snapshotObject == object): # ensures the same object is still selected from snapshots
        diff = snapshot1.snapshotDifference(snapshot2)
        snapshot3 = None
        if (mask == False):
            snapshot3 = copy.deepcopy(snapshot2)
        else:
            snapshot3 = copy.deepcopy(snapshot1)
        length = math.floor(len(diff) / displace)
        for i in range(length):
            if diff[i * displace: i * displace + displace] != (0, 0, 0, 0): # if there is a change in a pixel
                if (axis == pixelMapAxis and not(pixelMap is None)): # do it using the pixel map if able (NEED to add check to see if valid map for current texture)
                    if mask == False:
                        updatePixel(snapshot3, pixelMap[i].tolist(), snapshot2.pixels[i * displace : i * displace + displace])
                    else:
                        updatePixel(snapshot3, pixelMap[i].tolist(), snapshot1.pixels[i * displace : i * displace + displace])
                else:
                    tempUV = pixelToUV(i * displace, texture.size[0], texture.size[1])
                    tempPoint = getPointFromUV(object, tempUV, uv)
                    tempPointMirror = mirror3dCordinate(object, tempPoint, axis)
                    tempUVMirror = getUVFromPointOnModel(object, tempPointMirror, uv)
                    if mask == False: # copies changes found in the pixel between snapshot1 and snapshot2 over the mirror axis
                        updatePixel(snapshot3, uvToPixel(tempUVMirror, texture.size[0], texture.size[1]), snapshot2.pixels[i * displace : i * displace + displace])
                    else: # uses changed pixels as a mask for what to copy from snapshot1
                        updatePixel(snapshot3, uvToPixel(tempUVMirror, texture.size[0], texture.size[1]), snapshot1.pixels[i * displace : i * displace + displace])
        
        # does pixel gap fill if toggled
        if (pixelGapFillBool):
            pixelGapFill(snapshot2.snapshotDifference(snapshot3), snapshot3, threshold, selfBlend)
        texture.pixels = snapshot3.pixels # updates the textures pixels (very time expensive, so only done once at end)
    else:
        print("Error: Given object doesn't match object used to create snapshot")

# Inputs --------------------------
# object is a scene object
# texture is an image texture
# snapshot is an textureSnapshot (used as a faster alternative to the texture
# axis is axis letter ex. 'x', 'y', or 'z'
# uv is the string for the name of the UV map used
def createSnapshotMapping(object = None, texture = None, snapshot = None, axis = 'x', uv = "UVMap"):
    displace = 4
    length = 0
    pixelMap = None # Make it so the pixelMap is the size of the full mapping, but set to an out of bounds index like -1, -1. Then add all of the mappings, but skip it if the corresponding pair of pixels are already mapped (known by if the numbers in them aren't -1, -1). Also bind pairs together, so once you find a mapping for pixelA in pixelB, then pixelB can be set to have pixelA as its mapping.
    pixels = None
    sizeX = 0
    sizeY = 0
    if texture != None:
        length = math.floor(len(texture.pixels) / displace)
        pixelMap = np.full([length, 2], -1)
        sizeX = texture.size[0]
        sizeY = texture.size[1]
        pixels = texture.pixels
    elif snapshot != None:
        length = math.floor(len(snapshot.pixels) / displace)
        pixelMap = np.full([length, 2], -1)
        sizeX = snapshot.sizeX
        sizeY = snapshot.sizeY
        pixels = snapshot.pixels
    
    for i in range(length):
        if (pixelMap[i].tolist() == [-1, -1]): # only updates the mapping if it hasn't already been done
            tempUV = pixelToUV(i * displace, sizeX, sizeY)
            tempPoint = getPointFromUV(object, tempUV, uv)
            tempPointMirror = mirror3dCordinate(object, tempPoint, axis)
            tempUVMirror = getUVFromPointOnModel(object, tempPointMirror, uv)
            mirrorPixel = uvToPixel(tempUVMirror, sizeX, sizeY)
            pixelMap[i] = mirrorPixel # sets pixel A's mirror
            pixelMap[pixelCordToPixelNum(mirrorPixel, sizeX)] = pixelNumToPixelCord(pixelNum = i * 4, sizeX = sizeX, sizeY = sizeY) # set pixel B's mirror to pixel A

    return pixelMap

# Input: -----------------------------------------
# degrees is a float that is the measure of an angle in degrees
# Purpose: ---------------------------------------
# returns a 2D vector from an input of degrees as a measure of the angle
def normalVectorFromAngle(degrees):
    vector = np.array([math.cos((math.pi * degrees) / 180), math.sin((math.pi * degrees) / 180)])
    return vector

# value is the 2D cordinate as a vector in baseVectors1 that needs to be converted to baseVectors2
# newBase is the matrix representing the x, y base to be converted to
def convertBasis2D(value, newBase):
    invertedBase = np.linalg.inv(newBase)
    return (value.dot(invertedBase))

# function that helps perform the task of converting the input axis angle into a new basis
def newBasis(degrees):
    vector = np.zeros([2, 2])
    vector[0] = normalVectorFromAngle(degrees)
    vector[1] = normalVectorFromAngle(degrees + 90)
    return vector

# helper divide function that prevents divide by zero by returning zero if it were to happen
def safeDivide(num1, num2):
    if (num2 == 0):
        return 0
    else:
        return num1 / num2

# draws the symmetry line by inverting the pixels that lie upon it
# BUGS:
# - line is seemingly dotted, as a result of it inverting the same pixel mutliple times
def drawSymmetryLine(axisAngle, xPosition, yPosition, image):
    if (image is None):
        print("Error: No image is selected in image viewer")
        return False
    
    snapshot = textureSnapshot(image) # snapshots the image
    lineVector = normalVectorFromAngle(axisAngle)
    displace = 4
    if (lineVector[0] < 0.0001 and lineVector[0] > -0.0001): # correcting for tiny floating point errors
        lineVector[0] = 0
    if (lineVector[1] < 0.0001 and lineVector[1] > -0.0001):
        lineVector[1] = 0
    
    
    # gets the value for scaling the linevector in order to reach the edge of the UV, but has checks to ensure it doesn't choose zero
    temp = 0
    if (abs(safeDivide((1 - xPosition), lineVector[0])) > abs(safeDivide((1 - yPosition), lineVector[1])) and abs(safeDivide((1 - yPosition), lineVector[1])) != 0): # grabs more limiting multiplier for line vector
        temp = abs(safeDivide((1 - yPosition), lineVector[1]))
    elif (safeDivide((1 - xPosition), lineVector[0]) != 0):
        temp = abs(safeDivide((1 - xPosition), lineVector[0]))
    else:
        temp = abs(safeDivide((1 - yPosition), lineVector[1]))
    
    # sets up where the line would touch the end of the UV map
    endpointUV = np.multiply(lineVector, temp)
    endpointUV[0] = endpointUV[0] + xPosition
    endpointUV[1] = endpointUV[1] + yPosition
    # gets endpoint pixel in the direction of the line vector (represented as newBase)
    endpointPixel = uvToPixel(endpointUV.tolist(), image.size[0], image.size[1])

    # creates the array for moving the current UV
    addedVector = lineVector.copy()
    addedVector[0] = addedVector[0] / image.size[0]
    addedVector[1] = addedVector[1] / image.size[1]
    while (endpointUV[0] <= 1 and endpointUV[0] >= 0 and endpointUV[1] <= 1 and endpointUV[1] >= 0):
        # invert current pixel in snapshot
        tempVal = list(snapshot.pixels[pixelCordToPixelNum(endpointPixel, snapshot.sizeX) * displace : pixelCordToPixelNum(endpointPixel, snapshot.sizeX) * displace + displace])
        tempVal[0] = 1 - tempVal[0]
        tempVal[1] = 1 - tempVal[1]
        tempVal[2] = 1 - tempVal[2]
        tempVal[3] = 1 - tempVal[3]
        updatePixel(snapshot, endpointPixel, tempVal)
        # move the current UV cordinate over the required amount
        endpointUV = endpointUV - addedVector
        # move the current pixel over to the new UV position
        endpointPixel = uvToPixel(endpointUV.tolist(), image.size[0], image.size[1])
    
    # updates texture
    image.pixels = snapshot.pixels
    return True
    
        

# mirrors the changes from the snapshots, but does the mirror over the axis
def mirrorChangesFromSnapshots2D(snapshot1, snapshot2, image, axisAngle, xPosition, yPosition, mask = False, pixelGapFillBool=False, threshold=6, selfBlend=False):
    if (image is None):
        print("Error: No image is selected in image viewer")
        return False
    
    displace = 4
    diff = snapshot1.snapshotDifference(snapshot2)
    snapshot3 = None
    if (mask == False):
        snapshot3 = copy.deepcopy(snapshot2)
    else:
        snapshot3 = copy.deepcopy(snapshot1)
    # create the new basis
    newBase = newBasis(axisAngle)
    # use new basis to create a rotation matrix
    standardBase = np.array([[1, 0], [0, 1]])
    # loop through pixels that changes, converting them into the new basis, then flipping them over the axis by inversing their Y value. Remember to move the axis origin to the xPosition, yPosition
    length = math.floor(len(diff) / displace)
    for i in range(length):
        if diff[i * displace: i * displace + displace] != (0, 0, 0, 0): # if there is a change in a pixel
            tempUV = pixelToUV(i * displace, image.size[0], image.size[1]) # uv of current pixel
            tempUV = [tempUV[0] - xPosition, tempUV[1] - yPosition] # accounts for origin being at cursor
            newUV = convertBasis2D(np.array(tempUV), newBase) # converts to new base using the invert of the newBase
            newUV[1] = (newUV[1] * -1) # inverts y cordinate
            newUV = newUV.dot(newBase) # converts back to standard base by multiplying the value by its base (since its base is a representation from standard base)
            # changes origin back to the bottom left of the UV
            newUV[0] = newUV[0] + xPosition
            newUV[1] = newUV[1] + yPosition
            if (newUV[0] >= 0 and newUV[0] <= 1 and newUV[1] >= 0 and newUV[1] <= 1): # ensures within UV bounds
                if (mask == False):
                    updatePixel(snapshot3, uvToPixel(newUV.tolist(), image.size[0], image.size[1]), snapshot2.pixels[i * displace : i * displace + displace]) # updates pixel in snapshot
                else:
                    updatePixel(snapshot3, uvToPixel(newUV.tolist(), image.size[0], image.size[1]), snapshot1.pixels[i * displace : i * displace + displace]) # updates pixel in snapshot
    # does pixel gap fill if toggled
    if (pixelGapFillBool):
        pixelGapFill(snapshot2.snapshotDifference(snapshot3), snapshot3, threshold, selfBlend)
    image.pixels = snapshot3.pixels # updates the textures pixels (very time expensive, so only done once at end)
    return True

# MirrorChanges2D ----------------------------------------------------------------------
class MirrorChanges2D(bpy.types.Operator):
    """Texture Mirroring 2D For Image Editor""" # tooltip for menu items and buttons
    bl_idname = "image.mirror_changes_2d" # unique identifier for menu items (cannot contain capitals)
    bl_label = "Mirror Changes 2D" # display name
    bl_options = {'REGISTER', 'UNDO'} # Enables undo for the operator
    
    def execute(self, context): # function called when operation is run
        image = 0
        myPointers = context.scene.snapshotObjectPointer
        axisAngle = myPointers.axisAngle2D
        xValue = myPointers.position2Dx
        yValue = myPointers.position2Dy
        
        # grabs current selected image in image editor
        for area in context.screen.areas:
            if area.type == 'IMAGE_EDITOR':
                image = area.spaces.active.image
                snapshotChanges = textureSnapshot(image)# snapshots it, storing it in a value
                mirrorChangesFromSnapshots2D(bpy.types.Scene.snapshotOfOriginal, snapshotChanges, image, axisAngle, xValue, yValue, pixelGapFillBool=myPointers.pixelGapFillBool, threshold=myPointers.pixelGapFillThreshold, selfBlend=myPointers.pixelGapFillSelfBlend) # should make axis an input
        return {'FINISHED'} # Tells blender the operation is done
    
    #def invoke(self, context): # function used to help add input into the above execute (is called by default when operator is called)
        #return self.execute(context)

def menu_func_mirror_changes_2d(self, context):
    self.layout.operator(MirrorChanges2D.bl_idname)


# MirrorChanges2DAsMask ----------------------------------------------------------------------
class MirrorChanges2DAsMask(bpy.types.Operator):
    """Texture Mirroring 2D For Image Editor""" # tooltip for menu items and buttons
    bl_idname = "image.mirror_changes_2d_as_mask" # unique identifier for menu items (cannot contain capitals)
    bl_label = "Mirror Changes 2D As Mask" # display name
    bl_options = {'REGISTER', 'UNDO'} # Enables undo for the operator
    
    def execute(self, context): # function called when operation is run
        image = 0
        myPointers = context.scene.snapshotObjectPointer
        axisAngle = myPointers.axisAngle2D
        xValue = myPointers.position2Dx
        yValue = myPointers.position2Dy
        
        # grabs current selected image in image editor
        for area in context.screen.areas:
            if area.type == 'IMAGE_EDITOR':
                image = area.spaces.active.image
                snapshotChanges = textureSnapshot(image)# snapshots it, storing it in a value
                mirrorChangesFromSnapshots2D(bpy.types.Scene.snapshotOfOriginal, snapshotChanges, image, axisAngle, xValue, yValue, mask = True, pixelGapFillBool=myPointers.pixelGapFillBool, threshold=myPointers.pixelGapFillThreshold, selfBlend=myPointers.pixelGapFillSelfBlend) # should make axis an input
        return {'FINISHED'} # Tells blender the operation is done
    
    #def invoke(self, context): # function used to help add input into the above execute (is called by default when operator is called)
        #return self.execute(context)

def menu_func_mirror_changes_2d_as_mask(self, context):
    self.layout.operator(MirrorChanges2DAsMask.bl_idname)

# Draw Symmetry Line --------------------------------------------------------------------
class DrawSymmetryLine(bpy.types.Operator):
    """Draw Symmetry Line In Image Editor""" # tooltip for menu items and buttons
    bl_idname = "image.draw_symmetry_line" # unique identifier for menu items (cannot contain capitals)
    bl_label = "Invert Pixels On Symmetry Line" # display name
    bl_options = {'REGISTER', 'UNDO'} # Enables undo for the operator
    
    def execute(self, context): # function called when operation is run
        myPointers = context.scene.snapshotObjectPointer
        axisAngle = myPointers.axisAngle2D
        xValue = myPointers.position2Dx
        yValue = myPointers.position2Dy
        image = 0
        # grabs current selected image in image editor
        for area in bpy.context.screen.areas:
            if area.type == 'IMAGE_EDITOR':
                image = area.spaces.active.image
                drawSymmetryLine(axisAngle, xValue, yValue, image) # inverts pixels on the line
        return {'FINISHED'} # Tells blender the operation is done

def menu_func_snapshot(self, context):
    self.layout.operator(SnapshotOriginal.bl_idname)

# Snapshot Original --------------------------------------------------------------------
class SnapshotOriginal(bpy.types.Operator):
    """Snapshot Image In Image Editor""" # tooltip for menu items and buttons
    bl_idname = "image.snapshot_original" # unique identifier for menu items (cannot contain capitals)
    bl_label = "Snapshot" # display name
    bl_options = {'REGISTER', 'UNDO'} # Enables undo for the operator
    snapshot = textureSnapshot()
    
    def execute(self, context): # function called when operation is run
        myPointers = context.scene.snapshotObjectPointer
        # grabs current selected image in image editor
        for area in bpy.context.screen.areas:
            if area.type == 'IMAGE_EDITOR':
                image = area.spaces.active.image
                if (image is not None):
                    snapshot = textureSnapshot(image)# snapshots it, storing it in a value
                    bpy.types.Scene.snapshotOfOriginal = snapshot
                    bpy.types.Scene.snapshotObject = myPointers.selectedObject # stores what object was used to make the snapshot
                else:
                    print("Error: No image selected in image viewer")
        # adds required geometry node modifiers for 3D mirroring
        if (not validModifier(context.scene.snapshotObjectModifierPointUV, context.scene.snapshotObject, myPointers.selectedObject) or not validModifier(context.scene.snapshotObjectModifierPointModel, context.scene.snapshotObject, myPointers.selectedObject)): # makes sure the modifiers aren't already in there
            bpy.types.Scene.snapshotObjectModifierPointUV = addSamplePointOnUVFromModelModifier(myPointers.selectedObject)
            bpy.types.Scene.snapshotObjectModifierPointModel = addSamplePointOnModelFromUVModifier(myPointers.selectedObject)
        return {'FINISHED'} # Tells blender the operation is done

def menu_func_snapshot(self, context):
    self.layout.operator(SnapshotOriginal.bl_idname)

# revert to original snapshot
class SnapshotRevert(bpy.types.Operator):
    """Revert To Snapshot In Image Editor""" # tooltip for menu items and buttons
    bl_idname = "image.snapshot_revert" # unique identifier for menu items (cannot contain capitals)
    bl_label = "Revert to Snapshot" # display name
    bl_options = {'REGISTER', 'UNDO'} # Enables undo for the operator
    
    def execute(self, context): # function called when operation is run
        # grabs current selected image in image editor
        for area in bpy.context.screen.areas:
            if area.type == 'IMAGE_EDITOR':
                image = area.spaces.active.image
                snapshot = bpy.types.Scene.snapshotOfOriginal
        if (snapshot is not None):
            if (image.size[0] == snapshot.sizeX and image.size[1] == snapshot.sizeY): # ensures the texture and snapshot are the same size
                image.pixels = snapshot.pixels
            else:
                print("Error: Current texture and snapshot are of different sizes")
        else:
            print("Error: There is no snapshot to revert to")
        return {'FINISHED'} # Tells blender the operation is done

def menu_func_snapshot_revert(self, context):
    self.layout.operator(SnapshotRevert.bl_idname)


# Remove Snapshot Modifiers ----------------------------------------
class RemoveSnapshotModifiers(bpy.types.Operator):
    """Remove Snapshot Modifiers""" # tooltip for menu items and buttons
    bl_idname = "image.remove_snapshot_modifiers" # unique identifier for menu items (cannot contain capitals)
    bl_label = "Remove Snapshot Modifiers" # display name
    bl_options = {'REGISTER', 'UNDO'} # Enables undo for the operator
    
    def execute(self, context): # function called when operation is run
        myPointers = context.scene.snapshotObjectPointer
        myPointers.selectedObject.modifiers.remove(bpy.types.Scene.snapshotObjectModifierPointUV)
        myPointers.selectedObject.modifiers.remove(bpy.types.Scene.snapshotObjectModifierPointModel)
        
        return {'FINISHED'} # Tells blender the operation is done
    
def menu_func_remove_snapshot_modifiers(self, context):
    self.layout.operator(RemoveSnapshotModifiers.bl_idname)

# Mirror Changes --------------------------------------------------------------------
class MirrorChanges(bpy.types.Operator):
    """Texture Mirroring For Image Editor""" # tooltip for menu items and buttons
    bl_idname = "image.mirror_changes" # unique identifier for menu items (cannot contain capitals)
    bl_label = "Mirror Changes" # display name
    bl_options = {'REGISTER', 'UNDO'} # Enables undo for the operator
    
    def execute(self, context): # function called when operation is run
        image = 0
        myPointers = context.scene.snapshotObjectPointer
        # grabs current selected image in image editor
        for area in context.screen.areas:
            if area.type == 'IMAGE_EDITOR':
                image = area.spaces.active.image
                if (bpy.types.Scene.snapshotObject == myPointers.selectedObject): # ensures the same object is for snapshots is still being used
                    if (validModifier(context.scene.snapshotObjectModifierPointUV, context.scene.snapshotObject, myPointers.selectedObject) and validModifier(context.scene.snapshotObjectModifierPointModel, context.scene.snapshotObject, myPointers.selectedObject)): # makes sure the modifiers are already there
                        snapshotChanges = textureSnapshot(image)# snapshots it, storing it in a value
                        mirrorChangesFromSnapshots(bpy.types.Scene.snapshotOfOriginal, snapshotChanges, myPointers.selectedObject, image, self.axis, uv = myPointers.selectedUV, pixelMap = bpy.types.Scene.snapshotMapping, pixelMapAxis = bpy.types.Scene.snapshotMappingAxis, pixelGapFillBool=myPointers.pixelGapFillBool, threshold=myPointers.pixelGapFillThreshold, selfBlend=myPointers.pixelGapFillSelfBlend) # should make axis an input
                    else:
                        print("Error: Required modifiers are not on object. Try using snapshot again to add them back.")
                else:
                    print("Error: Snapshot objects do not match")
        return {'FINISHED'} # Tells blender the operation is done
    
    def invoke(self, context, axis): # function used to help add input into the above execute (is called by default when operator is called)
        self.axis = bpy.types.Scene.snapshotAxis # should change to whatever is selected in panel
        return self.execute(context)

def menu_func_mirror_changes(self, context):
    self.layout.operator(MirrorChanges.bl_idname)

# Mirror Changes As Mask --------------------------------------------------------------------
class MirrorChangesAsMask(bpy.types.Operator):
    """Texture Mirroring As Mask For Image Editor""" # tooltip for menu items and buttons
    bl_idname = "image.mirror_changes_as_mask" # unique identifier for menu items (cannot contain capitals)
    bl_label = "Mirror Changes As Mask" # display name
    bl_options = {'REGISTER', 'UNDO'} # Enables undo for the operator
    
    def execute(self, context): # function called when operation is run
        image = 0
        myPointers = context.scene.snapshotObjectPointer
        # grabs current selected image in image editor
        for area in context.screen.areas:
            if area.type == 'IMAGE_EDITOR':
                image = area.spaces.active.image
                if (bpy.types.Scene.snapshotObject == myPointers.selectedObject): # ensures the same object is for snapshots is still being used
                    if (validModifier(context.scene.snapshotObjectModifierPointUV, context.scene.snapshotObject, myPointers.selectedObject) and validModifier(context.scene.snapshotObjectModifierPointModel, context.scene.snapshotObject, myPointers.selectedObject)): # makes sure the modifiers are already there
                        snapshotChanges = textureSnapshot(image)# snapshots it, storing it in a value
                        image.pixels = bpy.types.Scene.snapshotOfOriginal.pixels # sets picture back to what it was in first snapshot
                        mirrorChangesFromSnapshots(bpy.types.Scene.snapshotOfOriginal, snapshotChanges, myPointers.selectedObject, image, self.axis, uv = myPointers.selectedUV, mask = True, pixelMap = bpy.types.Scene.snapshotMapping, pixelMapAxis = bpy.types.Scene.snapshotMappingAxis, pixelGapFillBool=myPointers.pixelGapFillBool, threshold=myPointers.pixelGapFillThreshold, selfBlend=myPointers.pixelGapFillSelfBlend) # should make axis an input
                    else:
                        print("Error: Required modifiers are not on object. Try using snapshot again to add them back.")
                else:
                    print("Error: Snapshot objects do not match")
        return {'FINISHED'} # Tells blender the operation is done
    
    def invoke(self, context, axis): # function used to help add input into the above execute (is called by default when operator is called)
        self.axis = bpy.types.Scene.snapshotAxis # should change to whatever is selected in panel
        return self.execute(context)

def menu_func_mirror_changes_as_mask(self, context):
    self.layout.operator(MirrorChangesAsMask.bl_idname)
    
# Create Mirror Mapping --------------------------------------------------------------------
class CreateMirrorMapping(bpy.types.Operator):
    """Create Mirror Mapping For Image Editor""" # tooltip for menu items and buttons
    bl_idname = "image.mirror_mapping" # unique identifier for menu items (cannot contain capitals)
    bl_label = "Create Mirror Map" # display name
    bl_options = {'REGISTER', 'UNDO'} # Enables undo for the operator
    
    def execute(self, context): # function called when operation is run
        image = 0
        myPointers = context.scene.snapshotObjectPointer
        # grabs current selected image in image editor
        for area in context.screen.areas:
            if area.type == 'IMAGE_EDITOR':
                image = area.spaces.active.image
                snapshotChanges = textureSnapshot(image)# snapshots it, storing it in a value
                if (bpy.types.Scene.snapshotObject == myPointers.selectedObject): # ensures the same object is for snapshots is still being used
                    if (validModifier(context.scene.snapshotObjectModifierPointUV, context.scene.snapshotObject, myPointers.selectedObject) and validModifier(context.scene.snapshotObjectModifierPointModel, context.scene.snapshotObject, myPointers.selectedObject)): # makes sure the modifiers are already there
                        if (bpy.types.Scene.snapshotMapping == None or bpy.types.Scene.snapshotMappingAxis != self.axis): # only makes a mapping if there isn't one or current one is on the wrong axis
                            bpy.types.Scene.snapshotMapping = createSnapshotMapping(object = myPointers.selectedObject, texture = image, snapshot = None, axis = self.axis, uv = myPointers.selectedUV) # makes a pixel map
                            bpy.types.Scene.snapshotMappingAxis = self.axis # updates what axis was used in the mapping
                    else:
                        print("Error: Required modifiers are not on object. Try using snapshot again to add them back.")
                else:
                    print("Error: Snapshot objects do not match")
        return {'FINISHED'} # Tells blender the operation is done
    
    def invoke(self, context, axis): # function used to help add input into the above execute (is called by default when operator is called)
        self.axis = bpy.types.Scene.snapshotAxis # should change to whatever is selected in panel
        return self.execute(context)

def menu_func_mirror_changes(self, context):
    self.layout.operator(MirrorChanges.bl_idname)
    
# Operators for choosing axis -----------------------
class ChooseXAxis(bpy.types.Operator):
    """Choose X Axis for Mirroring in Text Editor""" # tooltip for menu items and buttons
    bl_idname = "image.mirror_axis_x" # unique identifier for menu items (cannot contain capitals)
    bl_label = "X" # display name
    bl_options = {'REGISTER', 'UNDO'} # Enables undo for the operator
    
    def execute(self, context): # function called when operation is run
        bpy.types.Scene.snapshotAxis = 'x'
        return {'FINISHED'} # Tells blender the operation is done

def menu_func_mirror_axis_x(self, context):
    self.layout.operator(ChooseXAxis.bl_idname)
    
class ChooseYAxis(bpy.types.Operator):
    """Choose Y Axis for Mirroring in Text Editor""" # tooltip for menu items and buttons
    bl_idname = "image.mirror_axis_y" # unique identifier for menu items (cannot contain capitals)
    bl_label = "Y" # display name
    bl_options = {'REGISTER', 'UNDO'} # Enables undo for the operator
    
    def execute(self, context): # function called when operation is run
        bpy.types.Scene.snapshotAxis = 'y'
        return {'FINISHED'} # Tells blender the operation is done

def menu_func_mirror_axis_y(self, context):
    self.layout.operator(ChooseYAxis.bl_idname)
    
class ChooseZAxis(bpy.types.Operator):
    """Choose Z Axis for Mirroring in Text Editor""" # tooltip for menu items and buttons
    bl_idname = "image.mirror_axis_z" # unique identifier for menu items (cannot contain capitals)
    bl_label = "Z" # display name
    bl_options = {'REGISTER', 'UNDO'} # Enables undo for the operator
    
    def execute(self, context): # function called when operation is run
        bpy.types.Scene.snapshotAxis = 'z'
        return {'FINISHED'} # Tells blender the operation is done

def menu_func_mirror_axis_z(self, context):
    self.layout.operator(ChooseZAxis.bl_idname)

# Pointers For Addon -----------------------------------------
class MirrorAddonPointers(bpy.types.PropertyGroup):
    selectedObject : bpy.props.PointerProperty(
        name = "Object",
        description = "Object used for 3D mirroring",
        type = bpy.types.Object,
    )
    
    selectedUV : bpy.props.StringProperty(
        name = "UV",
        description = "UV mapped used in 3D mirroring",
        default = "UVMap",
    )
    
    position2Dx : bpy.props.FloatProperty(
        name = "2D X Position",
        description = "A UV position in X axis",
        default = 0.5,
        min = 0,
        max = 1,
    )
    
    position2Dy : bpy.props.FloatProperty(
        name = "2D Y Position",
        description = "A UV position in Y axis",
        default = 0.5,
        min = 0,
        max = 1,
    )
    
    axisAngle2D : bpy.props.FloatProperty(
        name = "Axis Angle",
        description = "Angle of 2D axis",
        default = 0,
        min = 0,
        max = 360,
    )
    
    pixelGapFillBool : bpy.props.BoolProperty(
        name = "Pixel Gap Fill",
        description = "Toggles whether pixel gap fill is used",
        default = False,
    )
    
    pixelGapFillThreshold : bpy.props.IntProperty(
        name = "Pixel Gap Fill Threshold",
        description = "Threshold of how many changed nearby pixels to decide if to fill",
        default = 6,
        min = 0,
        max = 8,
    )
    
    pixelGapFillSelfBlend : bpy.props.BoolProperty(
        name = "Pixel Gap Fill Self Blend",
        description = "Toggles whether pixel gap fill uses self blend (blending with the unchanged pixel it is on)",
        default = False,
    )

# Panel -------------------------------------
class MirrorAddonPanel(bpy.types.Panel):
    bl_label = "Settings" # lable for the tab inside the Panel tab
    bl_idname = "mirror_addon_panel"
    bl_space_type = 'IMAGE_EDITOR' # determines what window the panel is in
    bl_region_type = 'UI'
    bl_category = 'Mirroring' #label for the Panel tab
    
    def draw(self, context):
        layout = self.layout
        scene = context.scene
        myPointers = scene.snapshotObjectPointer
        
        #layout.label(text = "Test label")
        box = layout.box()
        box.label(text = "Mirror Settings")
        box.operator("image.snapshot_original") # creates a button that does the operation
        b1row1 = box.row()
        if (bpy.types.Scene.snapshotObject != None):
            b1row1.label(text = "Current Snapshot Object: " + bpy.types.Scene.snapshotObject.name)
        else:
            b1row1.label(text = "No Current Snapshot")
        b1row2 = box.row()
        b1row2.operator("image.snapshot_revert")
        b1row3 = box.row()
        b1row3.prop(myPointers, "selectedObject")
        b1row4 = box.row()
        b1row4.prop(myPointers, "selectedUV")
        
        # 2D Mirroring
        box2 = layout.box()
        box2.label(text = "Mirror 2D Settings")
        box2.operator("image.mirror_changes_2d")
        b2row1 = box2.row()
        b2row1.operator("image.mirror_changes_2d_as_mask")
        b2row2 = box2.row()
        b2row2.prop(myPointers, "position2Dx")
        b2row2.prop(myPointers, "position2Dy")
        b2row3 = box2.row()
        b2row3.prop(myPointers, "axisAngle2D")
        b2row4 = box2.row()
        b2row4.operator("image.draw_symmetry_line")
        
        # 3D Mirroring
        box3 = layout.box()
        box3.label(text = "Mirror 3D Settings")
        b3row1 = box3.row() # creates row in the box
        b3row1.operator("image.mirror_changes") # adds a button to the next row that is a button for its operator
        b3row2 = box3.row()
        b3row2.operator("image.mirror_changes_as_mask")
        b3row3 = box3.row()
        b3row3.operator("image.mirror_mapping")
        b5row4 = box3.row()
        if (bpy.types.Scene.snapshotMappingAxis != None):
            b5row4.label(text = "Mapping Axis: " + bpy.types.Scene.snapshotMappingAxis)
        else:
            b5row4.label(text = "No current mapping")
        b3row5 = box3.row()
        b3row5.operator("image.mirror_axis_x")
        b3row5.operator("image.mirror_axis_y")
        b3row5.operator("image.mirror_axis_z")
        b5row6 = box3.row()
        b5row6.label(text = "Current Selected Axis: " + bpy.types.Scene.snapshotAxis)
        b6row7 = box3.row()
        b6row7.operator("image.remove_snapshot_modifiers")
        
        # Pixel Gap Fill
        box4 = layout.box()
        box4.label(text = "Pixel Gap Fill Settings")
        b4row1 = box4.row()
        b4row1.prop(myPointers, "pixelGapFillBool")
        b4row2 = box4.row()
        b4row2.prop(myPointers, "pixelGapFillThreshold")
        b4row3 = box4.row()
        b4row3.prop(myPointers, "pixelGapFillSelfBlend")

# Registering Addon ---------------------------------------------

def register():
    # snapshot original
    bpy.utils.register_class(SnapshotOriginal)
    #bpy.types.IMAGE_MT_image.append(menu_func_snapshot) # adds operator to an existing menu
    # snapshot revert
    bpy.utils.register_class(SnapshotRevert)
    # mirror changes
    bpy.utils.register_class(MirrorChanges)
    #bpy.types.IMAGE_MT_image.append(menu_func_mirror_changes)
    # mirror changes as mask
    bpy.utils.register_class(MirrorChangesAsMask)
    # create mirror mapping
    bpy.utils.register_class(CreateMirrorMapping)
    # operators for panel help
    bpy.utils.register_class(ChooseXAxis)
    bpy.utils.register_class(ChooseYAxis)
    bpy.utils.register_class(ChooseZAxis)
    # remove snapshot modifiers
    bpy.utils.register_class(RemoveSnapshotModifiers)
    # mirror changes 2D
    bpy.utils.register_class(MirrorChanges2D)
    # mirror changes 2D as mask
    bpy.utils.register_class(MirrorChanges2DAsMask)
    # draw symmetry line
    bpy.utils.register_class(DrawSymmetryLine)
    # pointers class
    bpy.utils.register_class(MirrorAddonPointers)
    # panel
    bpy.utils.register_class(MirrorAddonPanel)
    # variables
    bpy.types.Scene.snapshotOfOriginal = textureSnapshot() # holds the snapshot
    bpy.types.Scene.snapshotMapping = None # holds the mapping for a snapshot for one axis
    bpy.types.Scene.snapshotAxis = 'x' # the axis currently selected
    bpy.types.Scene.snapshotMappingAxis = None # axis used in making the mapping
    bpy.types.Scene.snapshotObject = None # holds the object the snapshot was made on
    bpy.types.Scene.snapshotObjectModifierPointUV = None
    bpy.types.Scene.snapshotObjectModifierPointModel = None
    bpy.types.Scene.snapshotObjectPointer = bpy.props.PointerProperty(type=MirrorAddonPointers)
    
    
def unregister():
    bpy.utils.unregister_class(SnapshotOriginal)
    bpy.utils.unregister_class(SnapshotRevert)
    bpy.utils.unregister_class(MirrorChanges)
    bpy.utils.unregister_class(MirrorChangesAsMask)
    bpy.utils.unregister_class(CreateMirrorMapping)
    bpy.utils.unregister_class(ChooseXAxis)
    bpy.utils.unregister_class(ChooseYAxis)
    bpy.utils.unregister_class(ChooseZAxis)
    bpy.utils.unregister_class(RemoveSnapshotModifiers)
    bpy.utils.unregister_class(MirrorChanges2D)
    bpy.utils.unregister_class(MirrorChanges2DAsMask)
    bpy.utils.unregister_class(DrawSymmetryLine)
    bpy.utils.unregister_class(MirrorAddonPointers)
    bpy.utils.unregister_class(MirrorAddonPanel)
    del bpy.types.Scene.snapshotOfOriginal
    del bpy.types.Scene.snapshotMapping
    del bpy.types.Scene.snapshotAxis
    del bpy.types.Scene.snapshotMappingAxis
    del bpy.types.Scene.snapshotObject
    del bpy.types.Scene.snapshotObjectModifierPointUV
    del bpy.types.Scene.snapshotObjectModifierPointModel
    del bpy.types.Scene.snapshotObjectPointer

# For testing addon by running in text editor
if __name__ == "__main__":
    register()