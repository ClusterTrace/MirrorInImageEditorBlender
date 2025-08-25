# Mirror For 2D Texturing Addon

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
    "blender": (4,4,0),
    "category": "Texture",
}

import bpy
import mathutils
import math
import time
import copy
import numpy as np
import bmesh
import blf
import gpu
from gpu_extras.batch import batch_for_shader

timeDebug = True # Variable for checking the run times of the functions


# To Do:
#- look into making a loading bar and having blender not freeze up when mirroring large chunks or making the map
#- mirroring for 2D seems to wrap the mirror to the other side of the texture if an unusual angle or position for the symmetry line is used (might be an absolute value or something is preventing a negative value from going through or just the effect of tiling for the UVs)

#Known issues:
#- drawing over the mirror axis line or drawing on both sides of the mirror can cause drawing that is likely unwanted
#- 3D mirror sometimes has small pixel gaps caused by the point acquired from geometry nodes getting stuck on edges, as they stick outward more, or it is failing to read the corresponding pixel values for edges. Bandade fix is use a subdivision modifier so more face area exists or use Pixel Gap Fill
#- 2D mirroring will create small pixel gaps when mirroring on angles that are not multiples of 45 degrees. Bandade fix is to use Pixel Gap Fill
#- Addon has no way of telling if object it is using as a reference has had its geometry altered in between snapshot and mirror, which can cause undesired effects.
#- Geometry nodes and scripts likely run on cpu, which means expensive normally parallel computations like UV maps are far slower than they are supposed to be. Can't run cpu in parallel properly apparently in Blender (only runs one thread at a time)
#- Likely Doesn't work if there are overlapping UVs


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


def find_UV_cord_from_3D_point_on_model(ob, bm, cord, uv_layer, faces, testAgainst3DValue = False, threshold = 0.0005): # will return possibly weird values if given faces that align with the point, but the point isn't on (due to barymetric transform projecting). Fix is to use the testAgainst3DValue = True.
    for face in faces:
        if bmesh.geometry.intersect_face_point(face, cord):
            verts = [i.co for i in face.verts]
            uv1, uv2, uv3 = [l[uv_layer].uv.to_3d() for l in face.loops]
            bary_cordinates = mathutils.geometry.barycentric_transform(cord, *verts, uv1, uv2, uv3) # passed the 3D points of the face, then the 2D points of the face (the UV points) so it tranforms from 3D to UV
            uv = mathutils.Vector((bary_cordinates[0], bary_cordinates[1]))

            if (testAgainst3DValue): # makes sure the UV translates back to prevent issues of it working on faces that the projection works, but is not accurate for
                tempFaces = [face]
                temp3D = find_coord_on_3D_face_from_UV(uv, tempFaces, ob, uv_layer)
                if (not(temp3D is None)):
                    if ((temp3D - cord).magnitude < threshold):
                        return uv
            else:
                return uv


    return None # for if no position was found


# This function returns a cordinate on a given face that matches the position of a point on the UV
# Note: this requires the mesh be triangulated beauty wise and the uv_layer acquired from that
# Input:
# loc is a 2D vector location on the UV Ex. (0.5, 0.5)
# face is a faces from a bmesh to check to see if the point (loc) is on it
# ob is the object the faces are from
# uvs is a list of three values that act as a UV cordinate (three so it translates better to the 3D cordinate) Ex. (0.5, 0.5, 0)
def find_coord_3D_from_UV(loc, face, uvs, ob):
    uv1, uv2, uv3 = uvs
    x, y, z = [v.co for v in face.verts]
    co = mathutils.geometry.barycentric_transform(loc, uv1, uv2, uv3, x, y, z)
    return ob.matrix_world @ co # an important conversion to bring the world coordinate to the object's local space

# This function returns a cordinate on a given face that matches the position of a point on the UV
# Note: this requires the mesh be triangulated beauty wise and the uv_layer acquired from that
# Input:
# loc is a 2D vector location on the UV but as a mathutils Vector Ex. (0.5, 0.5)
# faces is a list of faces from a bmesh to check to see if the point (loc) is on them
# ob is the object the faces are from
# uv_layer is the UV layer being used that the loc is on
# Output:
# returns a 3D vector that is the location on the face or None if it fails to find an intersection
def find_coord_on_3D_face_from_UV(loc, faces, ob, uv_layer):
    if loc:
            loc_normalized = loc.to_3d()
    # finds the required point in 3D
    for face in faces:
        uv1, uv2, uv3 = [l[uv_layer].uv.to_3d() for l in face.loops]

        #print("trying", loc_normalized, "vs", uv1, uv2, uv3)
        if mathutils.geometry.intersect_point_tri_2d(loc_normalized, uv1, uv2, uv3):
            #print("found intersecting triangle")
            location_3D = find_coord_3D_from_UV(loc_normalized, face, (uv1, uv2, uv3), ob)
            return location_3D
    return None

# Alternative idea that manually does the barycentric cordinate calculation and tries to add a threshold for points near edges (buggy as allows points off faces to be mapped)
#def find_coord_on_3D_face_from_UV(loc, faces, ob, uv_layer):
#    if not loc:
#        return None

#    loc_normalized = loc.to_3d()

#    # First pass: try exact intersection
#    for face in faces:
#        uv1, uv2, uv3 = [l[uv_layer].uv.to_3d() for l in face.loops]
#        if mathutils.geometry.intersect_point_tri_2d(loc_normalized, uv1, uv2, uv3):
#            location_3D = find_coord_3D_from_UV(loc_normalized, face, (uv1, uv2, uv3), ob)
#            return location_3D

#    # Second pass: try with a small epsilon for edge cases #NOTE: this causes issues of allowing pixels outside of uv faces to be mapped to inner faces likely as a way of barycentric cordinates being a cordinate on the face so if it calculates one not on a face the result will be on a face
#    epsilon = 0.0001  # Small value for tolerance
#    for face in faces:
#        uv1, uv2, uv3 = [l[uv_layer].uv.to_3d() for l in face.loops]

#        # For edge cases, calculate barycentric coordinates directly
#        # and check if they're close enough to valid values
#        a = uv2 - uv1
#        b = uv3 - uv1
#        c = loc_normalized - uv1

#        # Area calculations
#        area_full = a.cross(b).length
#        if area_full < epsilon:  # Skip degenerate triangles
#            continue

#        # Calculate barycentric coordinates
#        u = a.cross(c).length / area_full
#        v = c.cross(b).length / area_full
#        w = 1.0 - u - v

#        # Check if point is close enough to triangle
#        if -epsilon <= u <= 1+epsilon and -epsilon <= v <= 1+epsilon and -epsilon <= w <= 1+epsilon:
#            # Clamp values to valid range
#            u = max(0, min(1, u))
#            v = max(0, min(1, v))
#            w = max(0, min(1, w))

#            # Normalize
#            total = u + v + w
#            if total > 0:
#                u /= total
#                v /= total
#                w /= total

#            # Get 3D coordinates
#            x, y, z = [vert.co for vert in face.verts]
#            co = x * u + y * v + z * w
#            return ob.matrix_world @ co

#    return None

# grabs the currently selected faces on an object's bmesh (from the 3D scene in edit mode, so not the basic bmesh) and returns them
def selectFacesFromEditModeSelection(tempBmesh):
    facesList = []
    tempFaces = tempBmesh.faces
    for f in tempFaces:
        if f.select:
            facesList.append(f)
    return facesList

# grabs faces if all of that faces vertices are selected. This is used to get around faces not being selected after triangulation of a bmesh
def selectFacesFromEditModeSelectionUsingVerticeSelection(tempBmesh):
    facesList = []
    tempFaces = tempBmesh.faces
    for f in tempFaces:
        count = 0
        for v in f.verts:
            if v.select:
                count = count + 1
        if (count == len(f.verts)):
            facesList.append(f)
    return facesList

# sets a face to be selected if all of that faces vertices are selected. This is used to get around faces not being selected after triangulation of a bmesh
def setFacesOfBmeshToSelectedIfAllVerticesSelected(tempBmesh):
    facesList = []
    tempFaces = tempBmesh.faces
    for f in tempFaces:
        count = 0
        for v in f.verts:
            if v.select:
                count = count + 1
        if (count == len(f.verts)):
            f.select = True
    return facesList

# grabs all faces from a bmesh (important, as passing the faces directly passes a wierd pointer that counts as one face)
def selectAllFacesOfBmesh(tempBmesh):
    facesList = []
    tempFaces = tempBmesh.faces
    for f in tempFaces:
        if f.select:
            facesList.append(f)
    return facesList

# Inputs: --------------
# diff is the difference of the before mirror snapshot and the one after mirroring)
# snapshot is the textureSnapshot that is being edited (one after mirroring)
# selfBlend is a boolean for whether the unchanged pixel should factor in its own value to the blend
# This function takes the diff (the difference between snapshots made in things like the mirror functions) and the new snapshot to be able to try and guess which pixels need to be filled in to fix random gaps made in mirroring
# This function only checks the left and right pixel, as this is the pixelGapFill used for the 3D mirroring, which due to distortion on curved surfaces and floating point precision issues will have vertical pixel gaps (likely from converting back into a UV cordinate)
def pixelGapFill(diff, snapshot, selfBlend=False):
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
        left = pixelCordToPixelNum([currentPixel[0] - 1, currentPixel[1]], snapshot.sizeX, snapshot.sizeY)
        right = pixelCordToPixelNum([currentPixel[0] + 1, currentPixel[1]], snapshot.sizeX, snapshot.sizeY)

        if ((currentPixel[0] - 1) > 0): # check if pixel is possible (left)
            if diff[left * displace: left * displace + displace] != (0, 0, 0, 0):
                changedPixels.append(left)
        if ((currentPixel[0] + 1) < snapshot.sizeX): # check if pixel is possible (right)
            if diff[right * displace: right * displace + displace] != (0, 0, 0, 0):
                changedPixels.append(right)

        # if enough pixels are changed, then update the pixel to be a mix of its changed neighbors
        if (len(changedPixels) >= 2):
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

# Inputs: --------------
# diff is the difference of the before mirror snapshot and the one after mirroring)
# snapshot is the textureSnapshot that is being edited (one after mirroring)
# threshold is an integer for how many adjacent pixels must be different in the snapshot to require blending (averaging the pixels value to nearby ones)
# selfBlend is a boolean for whether the unchanged pixel should factor in its own value to the blend
# This function takes the diff (the difference between snapshots made in things like the mirror functions) and the new snapshot to be able to try and guess which pixels need to be filled in to fix random gaps made in mirroring
def pixelGapFillThreshold(diff, snapshot, threshold=6, selfBlend=False):
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
    #tempPoint = mathutils.Vector(point)
    tempPoint = point - object.location # moves the origin to be where the object is
    if axis == 'x':
        tempPoint[0] = tempPoint[0] * -1
    elif axis == 'y':
        tempPoint[1] = tempPoint[1] * -1
    elif axis == 'z':
        tempPoint[2] = tempPoint[2] * -1
    else:
        print("Error: axis input not valid")
        return point
    tempPoint = tempPoint + object.location # adds the object's displacement back
    return tempPoint

# Inputs: ------------
# snapshot1 is a textureSnapshot
# snapshot2 is a textureSnapshot, expected to be of the same image dimensions of snapshot1
# object is an object from the scene
# tempBmesh is the bmesh of the object that holds the faces
# texture is a image texture
# axis is a character, expected to be x, y, or z
# uv is the string for the name of the UV map used
# faces is the list of faces from the bmesh to check against
# mask is a boolean for whether the changes are used as a mask or not
# pixelMap is a 2D list or array of how the pixels are mapped to their mirror (stores the mirror cordinate)
# pixelMapAxis is the axis the mirror cordinates used in the pixelMap (Ex. 'x', 'y', or 'z')
# Purpose: ---------
# This function performs the changes or the mirroring of information from the snapshots
def mirrorChangesFromSnapshots(snapshot1, snapshot2, object, tempBmesh, texture, axis, uv = "UVMap", faces = [], mask = False, pixelMap = None, pixelMapAxis = None):
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
                if (pixelMap is None):
                    pixelMap = np.full([length, 2], -1)
                if (axis == pixelMapAxis and not(pixelMap[i].tolist() == [-1, -1])): # do it using the pixel map if able (TODO: add check to see if valid map for current texture)
                    if mask == False:
                        updatePixel(snapshot3, pixelMap[i].tolist(), snapshot2.pixels[i * displace : i * displace + displace])
                    else:
                        updatePixel(snapshot3, pixelMap[i].tolist(), snapshot1.pixels[i * displace : i * displace + displace])
                else: # calculates the mirror if not stored in the mapping and updates or replaces the existing mapping to store this mirror
                    #print("Length: " + str(len(faces)))
                    tempUV = pixelToUV(i * displace, texture.size[0], texture.size[1])
                    tempUV = mathutils.Vector(tempUV) # converts the list to a vector
                    tempPoint = find_coord_on_3D_face_from_UV(tempUV, faces, object, tempBmesh.loops.layers.uv[uv])
                    #print("TempPoint: " + str(tempPoint)) # REMOVE
                    if (tempPoint != None): # prevents trying to mirror points that didn't land on the model
                        tempPointMirror = mirror3dCordinate(object, tempPoint, axis)
                        #print("TempPointMirror: " + str(tempPointMirror)) # REMOVE
                        tempUVMirror = find_UV_cord_from_3D_point_on_model(object, tempBmesh, tempPointMirror, tempBmesh.loops.layers.uv[uv], tempBmesh.faces, True, 0.0005)
                        #print("tempUVMirror: " + str(tempUVMirror)) # REMOVE
                        if (tempUVMirror != None): # prevents trying to mirror for when the mirror doesn't land (Ex. when the mesh isn't symmetric or isn't symmetric on the currently selected axis)
                            tempPixelLoc = uvToPixel(tempUVMirror, texture.size[0], texture.size[1])
                            pixelMap[i] = tempPixelLoc # updates the pixelMap to contain the mapping for pixel A to pixel B
                            pixelMap[pixelCordToPixelNum(tempPixelLoc, texture.size[0])] = pixelNumToPixelCord(pixelNum = i * displace, sizeX = texture.size[0], sizeY = texture.size[1]) # set pixel B's mirror to pixel A
                            if mask == False: # copies changes found in the pixel between snapshot1 and snapshot2 over the mirror axis
                                updatePixel(snapshot3, tempPixelLoc, snapshot2.pixels[i * displace : i * displace + displace])
                            else: # uses changed pixels as a mask for what to copy from snapshot1
                                updatePixel(snapshot3, tempPixelLoc, snapshot1.pixels[i * displace : i * displace + displace])


        bpy.types.Scene.snapshotDiff = snapshot2.snapshotDifference(snapshot3) # stores difference for pixelGapFilling
        bpy.types.Scene.snapshotMapping = pixelMap # updates the pixelMapping with what was learned in this mirroring
        #if (pixelGapFillVerticalLines): # does pixel gap fill if toggled
            #pixelGapFill(snapshot2.snapshotDifference(snapshot3), snapshot3, selfBlend)
        texture.pixels = snapshot3.pixels # updates the textures pixels (very time expensive, so only done once at end)
    else:
        print("Error: Given object doesn't match object used to create snapshot")

# Inputs --------------------------
# object is a scene object
# tempBmehs is the bmesh of the object
# texture is an image texture
# snapshot is an textureSnapshot (used as a faster alternative to the texture)
# axis is axis letter ex. 'x', 'y', or 'z'
# uv is the string for the name of the UV map used
# pixelMap is the array for storing the cordinates a pixel corresponds to
def createSnapshotMapping(object = None, tempBmesh = None, texture = None, snapshot = None, axis = 'x', uv = "UVMap", pixelMap = None):
    displace = 4
    length = 0
    pixels = None
    sizeX = 0
    sizeY = 0
    if texture != None:
        length = math.floor(len(texture.pixels) / displace)
        #pixelMap = np.full([length, 2], -1)
        sizeX = texture.size[0]
        sizeY = texture.size[1]
        pixels = texture.pixels
    elif snapshot != None:
        length = math.floor(len(snapshot.pixels) / displace)
        #pixelMap = np.full([length, 2], -1)
        sizeX = snapshot.sizeX
        sizeY = snapshot.sizeY
        pixels = snapshot.pixels


    if (pixelMap is None):
        pixelMap = np.full([length, 2], -1) # Make it so the pixelMap is the size of the full mapping, but set to an out of bounds index like -1, -1. Then add all of the mappings, but skip it if the corresponding pair of pixels are already mapped (known by if the numbers in them aren't -1, -1). Also bind pairs together, so once you find a mapping for pixelA in pixelB, then pixelB can be set to have pixelA as its mapping.

    if (tempBmesh != None):
        for i in range(length):
            if (pixelMap[i].tolist() == [-1, -1] or axis != bpy.types.Scene.snapshotMappingAxis): # only updates the mapping if it hasn't already been done
                tempUV = pixelToUV(i * displace, sizeX, sizeY)
                tempUV = mathutils.Vector(tempUV) # converts the list to a vector
                tempPoint = find_coord_on_3D_face_from_UV(tempUV, tempBmesh.faces, object, tempBmesh.loops.layers.uv[uv])
                if (tempPoint != None): # prevents trying to mirror points that didn't land on the model (This means some pixels will not have a corresponding mirrored pixel value mapped)
                    tempPointMirror = mirror3dCordinate(object, tempPoint, axis)
                    tempUVMirror = find_UV_cord_from_3D_point_on_model(object, tempBmesh, tempPointMirror, tempBmesh.loops.layers.uv[uv], tempBmesh.faces, True, 0.0005)
                    if (tempUVMirror != None): # prevents trying to mirror for when the mirror doesn't land (Ex. when the mesh isn't symmetric or isn't symmetric on the currently selected axis)
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

# Draw handler for the Image Editor to draw a symmetry line
def draw_symmetry_line_callback():
    context = bpy.context
    if context.area is None:
        return

    scene = context.scene
    props = scene.symmetry_line_props # gets line properties
    addonProps = scene.snapshotObjectPointer # gets addon properties

    # Check if we're in the image editor and symmetry line is enabled
    if not props.enabled or context.area.type != 'IMAGE_EDITOR':
        return

    # Get image editor space and image
    space = context.area.spaces.active
    image = space.image
    if not image:
        return

    region = context.region

    # Use Blender's view2d to convert between image space and screen space
    view2d = region.view2d

    # Create points in image space - one at the bottom of the image and one at the top
    # Each point is (x,y) Numbers are in range of 0-1 for the x and y values, so to extend beyond the image borders give values above 1 or below 0
    axisAngle = addonProps.axisAngle2D
    xPosition = addonProps.position2Dx
    yPosition = addonProps.position2Dy

    lineVector = normalVectorFromAngle(axisAngle)
    if (lineVector[0] < 0.0001 and lineVector[0] > -0.0001): # correcting for tiny floating point errors
        lineVector[0] = 0
    if (lineVector[1] < 0.0001 and lineVector[1] > -0.0001):
        lineVector[1] = 0


    # gets the value for scaling the linevector in order to reach the edge of the UV, but has checks to ensure it doesn't choose zero
    temp = 0
    temp2 = 0
    if (abs(safeDivide((1 - xPosition), lineVector[0])) > abs(safeDivide((1 - yPosition), lineVector[1])) and abs(safeDivide((1 - yPosition), lineVector[1])) != 0): # grabs more limiting multiplier for line vector
        temp = abs(safeDivide((1 - yPosition), lineVector[1]))
    elif (safeDivide((1 - xPosition), lineVector[0]) != 0):
        temp = abs(safeDivide((1 - xPosition), lineVector[0]))
    else:
        temp = abs(safeDivide((1 - yPosition), lineVector[1]))

    # sets up where the line would touch the end of the UV map
    lineVectorPos = np.multiply(lineVector, temp + 1) # adds 1 to temp to ensure that the line point positions are off the image, else can result in the line endinging on the image
    endpointUV = [lineVectorPos[0] + xPosition, lineVectorPos[1] + yPosition]
    startPointUV = [xPosition - lineVectorPos[0], yPosition - lineVectorPos[1]]

    line_img_bottom = (startPointUV[0], startPointUV[1]) #line_img_bottom = (line_img_x, 0) # first point of line
    line_img_top = (endpointUV[0], endpointUV[1]) #line_img_top = (line_img_x, 1) # second point of line

    # Convert image space coordinates to region (screen) space
    line_screen_bottom = view2d.view_to_region(*line_img_bottom, clip=False)
    line_screen_top = view2d.view_to_region(*line_img_top, clip=False)


    # Print debug info
#    print(f"Line position: {props.position}")
#    print(f"Image coordinates: bottom={line_img_bottom}, top={line_img_top}")
#    print(f"Screen coordinates: bottom={line_screen_bottom}, top={line_screen_top}")

    # Draw the line using GPU
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    vertices = (
        (line_screen_bottom[0], line_screen_bottom[1]),
        (line_screen_top[0], line_screen_top[1])
    )
    batch = batch_for_shader(shader, 'LINES', {"pos": vertices})

    shader.bind()
    shader.uniform_float("color", props.color)
    gpu.state.line_width_set(props.line_thickness)
    batch.draw(shader)

# draws the symmetry line by inverting the pixels that lie upon it
# BUGS:
# - line is seemingly dotted, as a result of it inverting the same pixel mutliple times
def drawSymmetryLineUsingInvert(axisAngle, xPosition, yPosition, image):
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

# Helper functions for mirrorChangesFromSnapshotUsingBakingWithMask ------------
# duplicate a given object in the scene
def duplicate_object_in_scene(obj):
    testObject = bpy.data.objects.new(obj.name, obj.data.copy()) # creates a duplicate object
    bpy.context.scene.collection.objects.link(testObject) # links the created object to the scene
    return testObject

# create a new material with an image as the input for the color
def new_material_using_image(img):
    newMaterial = bpy.data.materials.new("MirroringMaterial")
    newMaterial.use_nodes = True
    nodeTree = newMaterial.node_tree
    nodes = newMaterial.node_tree.nodes
    # makes/gets requires nodes
    textureNode = nodes.new('ShaderNodeTexImage')
    principledNode = nodes.new('ShaderNodeBsdfPrincipled')
    # gets output node
    outputNode = 0
    for i in range(0, len(nodes)):
        if (nodes[i].type == 'OUTPUT_MATERIAL'):
            outputNode = nodes[i]
    # connects nodes
    newMaterial.node_tree.links.new(textureNode.outputs['Color'], principledNode.inputs['Base Color'])
    newMaterial.node_tree.links.new(principledNode.outputs['BSDF'], outputNode.inputs['Surface'])
    # sets active node selection and image
    textureNode.select = True
    nodes.active = textureNode
    textureNode.image = img
    return newMaterial

def deleteMaterialFromScene(material):
    material.user_clear() # removes all links, meaning removes from any objects
    bpy.data.materials.remove(material, do_unlink=True) # removes material

# function for performing the mirroring using baking with mask
def mirrorChangesFromSnapshotUsingBakingWithMask(snapshot1, snapshot2, obj, image, axis, extrusion, uvmap):
    if (image is None):
        print("Error: No image is selected in image viewer")
        return False

    displace = 4
    diff = snapshot1.snapshotDifference(snapshot2)
    snapshot3 = copy.deepcopy(snapshot1)

    mirrorScale = [-1, 1, 1] # defaults to x
    if (axis == 'z'):
        mirrorScale = [1, 1, -1]
    elif (axis == 'y'):
        mirrorScale = [1, -1, 1]


    # get the mirror of the texture ------------------------
    # sets the render mode to cycles
    bpy.context.scene.render.engine = 'CYCLES'
    # sets mode to object mode
    bpy.ops.object.mode_set(mode='OBJECT')
    # duplicate the current object (call this object the duplicate object from here on)
    duplicateObject = duplicate_object_in_scene(obj)
    duplicateObject.data.materials.clear() # clears materials from object
    # give the duplicate object a new material with the image used in the new material
    bakingImage = bpy.data.images.new(name="TempImageForMirroring", width=image.size[0], height=image.size[1])
    newMaterial = new_material_using_image(bakingImage)
    duplicateObject.data.materials.append(newMaterial) # adds the material to duplicateObject
    duplicateObject.active_material_index = len(duplicateObject.data.materials) - 1 # sets the last material to be selected (should be the material just added)
    # duplicate the duplicate object and scale it inversely on an axis (call this object the inverse duplicate object from here on)
    inverseObject = duplicate_object_in_scene(duplicateObject)
    inverseObject.data.materials.clear() # clears materials from object
    newInverseObjectMaterial = new_material_using_image(image)
    inverseObject.data.materials.append(newInverseObjectMaterial) # adds the material to inverseObject
    inverseObject.active_material_index = len(duplicateObject.data.materials) - 1 # sets the last material to be selected (should be the material just added)
    inverseObject.scale =  mathutils.Vector([inverseObject.scale[0] * mirrorScale[0], inverseObject.scale[1] * mirrorScale[1], inverseObject.scale[2] * mirrorScale[2]]) # inverses on the selected axis
    # bake the inverse duplicate object onto the duplicate object
    bpy.ops.object.select_all(action='DESELECT')
    duplicateObject.select_set(True)
    inverseObject.select_set(True)
    bpy.context.view_layer.objects.active = duplicateObject #sets required active object (ex. bpy.context.view_layer.objects.active = obj)
    bpy.ops.object.bake(type='DIFFUSE', pass_filter={'COLOR'}, use_selected_to_active=True, max_ray_distance=extrusion + 0.001, cage_extrusion=extrusion, use_clear=True, uv_layer=uvmap) # tries to bake with the correct settings (bpy.ops.object.bake(type='DIFFUSE'))
    # delete the objects and materials created
    bpy.data.objects.remove(duplicateObject) # only really have to delete the objects, as the materials should have no users once the objects duplicateObject and inverseObject are deleted
    bpy.data.objects.remove(inverseObject)
    deleteMaterialFromScene(newMaterial)
    deleteMaterialFromScene(newInverseObjectMaterial)
    snapshot4 = textureSnapshot(bakingImage) # gets the mirror of the texture
    bpy.data.images.remove(bakingImage, do_unlink=True, do_id_user=True, do_ui_user=True) # deletes the texture
    # use the diff as a mask to determine what should be the mirror of the texture ---------------------
    length = math.floor(len(diff) / displace)
    for i in range(length):
        if diff[i * displace: i * displace + displace] != (0, 0, 0, 0): # if there is a change in a pixel
            updatePixel(snapshot3, pixelNumToPixelCord(i * displace, snapshot3.sizeX, snapshot3.sizeY), snapshot4.pixels[i * displace : i * displace + displace])
    # return the updated texture that contains the mirror
    return snapshot3


# mirrors the changes from the snapshots, but does the mirror over the axis
def mirrorChangesFromSnapshots2D(snapshot1, snapshot2, image, axisAngle, xPosition, yPosition, mask = False):
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
            #tempUV = pixelToUV(i * displace, image.size[0], image.size[1]) # uv of current pixel
            tempPixel = pixelNumToPixelCord(pixelNum = i * 4, sizeX = snapshot1.sizeX, sizeY = snapshot1.sizeY)
            #tempUV = [tempUV[0] - xPosition, tempUV[1] - yPosition] # accounts for origin being at cursor
            tempPixel[0] = tempPixel[0] - (xPosition * (snapshot1.sizeX - 1))
            tempPixel[1] = tempPixel[1] - (yPosition * (snapshot1.sizeY - 1))
            newPixel = convertBasis2D(np.array(tempPixel), newBase) # converts to new base using the invert of the newBase
            newPixel[1] = (newPixel[1] * -1) # inverts y cordinate to mirror
            newPixel = newPixel.dot(newBase) # converts back to standard base by multiplying the value by its base (since its base is a representation from standard base)
            # changes origin back to the bottom left of the UV
            newPixel[0] = newPixel[0] + (xPosition * (snapshot1.sizeX - 1))
            newPixel[1] = newPixel[1] + (yPosition * (snapshot1.sizeY - 1))
            newPixel = [round(newPixel[0]), round(newPixel[1])]
            if (mask == False):
                updatePixel(snapshot3, newPixel, snapshot2.pixels[i * displace : i * displace + displace]) # updates pixel in snapshot
            else:
                updatePixel(snapshot3, newPixel, snapshot1.pixels[i * displace : i * displace + displace]) # updates pixel in snapshot

    bpy.types.Scene.snapshotDiff = snapshot2.snapshotDifference(snapshot3) # stores difference for pixelGapFilling
    #if (pixelGapFillVerticalLines): # does pixel gap fill if toggled
        #pixelGapFillThreshold(snapshot2.snapshotDifference(snapshot3), snapshot3, threshold, selfBlend)
    image.pixels = snapshot3.pixels # updates the textures pixels (very time expensive, so only done once at end)
    return True

# Old Float UV method that suffered from float precision issues causes slight pixel offsets and issues of pixel offsets related to texture boundary
# Possibly fixable by scaling the UV cord to be the size of the texture to help reduce floating point precision issues
# mirrors the changes from the snapshots, but does the mirror over the axis
def mirrorChangesFromSnapshots2D_Old(snapshot1, snapshot2, image, axisAngle, xPosition, yPosition, mask = False):
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
            newUV[1] = (newUV[1] * -1) # inverts y cordinate to mirror
            newUV = newUV.dot(newBase) # converts back to standard base by multiplying the value by its base (since its base is a representation from standard base)
            # changes origin back to the bottom left of the UV
            newUV[0] = newUV[0] + xPosition
            newUV[1] = newUV[1] + yPosition
            if (newUV[0] >= 0 and newUV[0] <= 1 and newUV[1] >= 0 and newUV[1] <= 1): # ensures within UV bounds
                if (mask == False):
                    updatePixel(snapshot3, uvToPixel(newUV.tolist(), image.size[0], image.size[1]), snapshot2.pixels[i * displace : i * displace + displace]) # updates pixel in snapshot
                else:
                    updatePixel(snapshot3, uvToPixel(newUV.tolist(), image.size[0], image.size[1]), snapshot1.pixels[i * displace : i * displace + displace]) # updates pixel in snapshot

    bpy.types.Scene.snapshotDiff = snapshot2.snapshotDifference(snapshot3) # stores difference for pixelGapFilling
    #if (pixelGapFillVerticalLines): # does pixel gap fill if toggled
        #pixelGapFillThreshold(snapshot2.snapshotDifference(snapshot3), snapshot3, threshold, selfBlend)
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
        startTime = time.time()
        for area in context.screen.areas:
            if area.type == 'IMAGE_EDITOR':
                image = area.spaces.active.image
                snapshotChanges = textureSnapshot(image)# snapshots it, storing it in a value
                mirrorChangesFromSnapshots2D(bpy.types.Scene.snapshotOfOriginal, snapshotChanges, image, axisAngle, xValue, yValue) # should make axis an input
        if (timeDebug): # TIME
            print("MirrorChanges2D time: " + str(time.time() - startTime))
        return {'FINISHED'} # Tells blender the operation is done

    #def invoke(self, context): # function used to help add input into the above execute (is called by default when operator is called)
        #return self.execute(context)

def menu_func_mirror_changes_2d(self, context):
    self.layout.operator(MirrorChanges2D.bl_idname)


# MirrorChanges2DAsMask ----------------------------------------------------------------------
class MirrorChanges2DAsMask(bpy.types.Operator):
    """Texture Mirroring 2D as mask for Image Editor. Recommend using an inverting brush or a white brush set to exclusion on blending for masking.""" # tooltip for menu items and buttons
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
        startTime = time.time()
        for area in context.screen.areas:
            if area.type == 'IMAGE_EDITOR':
                image = area.spaces.active.image
                snapshotChanges = textureSnapshot(image)# snapshots it, storing it in a value
                mirrorChangesFromSnapshots2D(bpy.types.Scene.snapshotOfOriginal, snapshotChanges, image, axisAngle, xValue, yValue, mask = True) # should make axis an input
        if (timeDebug): # TIME
            print("MirrorChanges2DAsMask time: " + str(time.time() - startTime))
        return {'FINISHED'} # Tells blender the operation is done

    #def invoke(self, context): # function used to help add input into the above execute (is called by default when operator is called)
        #return self.execute(context)

def menu_func_mirror_changes_2d_as_mask(self, context):
    self.layout.operator(MirrorChanges2DAsMask.bl_idname)

# below is not used, as replaced by a draw call to the GPU for a line
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
        startTime = time.time()
        for area in bpy.context.screen.areas:
            if area.type == 'IMAGE_EDITOR':
                image = area.spaces.active.image
                drawSymmetryLineUsingInvert(axisAngle, xValue, yValue, image) # inverts pixels on the line
        if (timeDebug): # TIME
            print("MDrawSymmetryLine time: " + str(time.time() - startTime))

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
        startTime = time.time()
        for area in bpy.context.screen.areas:
            if area.type == 'IMAGE_EDITOR':
                image = area.spaces.active.image
                if (image is not None):
                    snapshot = textureSnapshot(image)# snapshots it, storing it in a value
                    bpy.types.Scene.snapshotOfOriginal = snapshot
                    bpy.types.Scene.snapshotObject = myPointers.selectedObject # stores what object was used to make the snapshot
                else:
                    print("Error: No image selected in image viewer")

        if (timeDebug): # TIME
            print("SnapshotOriginal time: " + str(time.time() - startTime))
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
        startTime = time.time()
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
        if (timeDebug): # TIME
            print("SnapshotRevert time: " + str(time.time() - startTime))
        return {'FINISHED'} # Tells blender the operation is done

def menu_func_snapshot_revert(self, context):
    self.layout.operator(SnapshotRevert.bl_idname)

# Mirror Changes --------------------------------------------------------------------
def MirrorChangesHelperFunction(self, context, masking):
    image = 0
    myPointers = context.scene.snapshotObjectPointer
    faceSelectionMethod = str(myPointers.faceSelectionMethodEnum) # face selection method variable
    # grabs current selected image in image editor
    for area in context.screen.areas:
        if area.type == 'IMAGE_EDITOR':
            image = area.spaces.active.image
            if (bpy.types.Scene.snapshotObject == myPointers.selectedObject): # ensures the same object is for snapshots is still being used
                if (myPointers.selectedObject.type == 'MESH'): # makes sure the object type is right
                    snapshotChanges = textureSnapshot(image)# snapshots it, storing it in a value
                    # creates a bmesh
                    tempBmesh = bmesh.new()
                    if (faceSelectionMethod == 'Edit_Mode_Selection'): # a setup required for the selectFacesFromEditModeSelection performed later
                        if (myPointers.selectedObject.mode == 'EDIT'):
                            bpy.ops.object.mode_set(mode='OBJECT') # sets to object mode to flush the selection in edit mode
                            bpy.ops.object.mode_set(mode='EDIT') # sets to edit mode to revert to the state before changed
                    tempBmesh.from_mesh(myPointers.selectedObject.data)
                    tempBmesh.faces.ensure_lookup_table()
                    # gets faces
                    faces = []
                    bmesh.ops.triangulate(tempBmesh, faces=tempBmesh.faces, quad_method='BEAUTY', ngon_method='BEAUTY') # needs to be triangulated for the barymetric transformation
                    # face selection methods (defaults to use all faces)
                    if (faceSelectionMethod == 'Edit_Mode_Selection'):
                            faces = selectFacesFromEditModeSelectionUsingVerticeSelection(tempBmesh) # have to check using vertices as triangulation breaks the face selection
                    else:
                        faces = tempBmesh.faces
                    mirrorChangesFromSnapshots(bpy.types.Scene.snapshotOfOriginal, snapshotChanges, myPointers.selectedObject, tempBmesh, image, self.axis, uv = myPointers.selectedUV, faces = faces, mask = masking, pixelMap = bpy.types.Scene.snapshotMapping, pixelMapAxis = bpy.types.Scene.snapshotMappingAxis)
                    tempBmesh.free()
                else:
                    print("Error: Object selected is not a MESH object")
            else:
                print("Error: Snapshot objects do not match")

class MirrorChanges(bpy.types.Operator):
    """Texture Mirroring For Image Editor""" # tooltip for menu items and buttons
    bl_idname = "image.mirror_changes" # unique identifier for menu items (cannot contain capitals)
    bl_label = "Mirror Changes" # display name
    bl_options = {'REGISTER', 'UNDO'} # Enables undo for the operator

    def execute(self, context): # function called when operation is run
        startTime = time.time()
        if (bpy.types.Scene.snapshotMapping is None or self.axis != bpy.types.Scene.snapshotMappingAxis): # if the mapping is none, then it is instantiated within the mirrorChanges function, so updating axis to account for this
            bpy.types.Scene.snapshotMappingAxis = self.axis
        MirrorChangesHelperFunction(self, context, False)
        if (timeDebug): # TIME
            print("MirrorChanges time: " + str(time.time() - startTime))
        return {'FINISHED'} # Tells blender the operation is done

    def invoke(self, context, axis): # function used to help add input into the above execute (is called by default when operator is called)
        self.axis = bpy.types.Scene.snapshotAxis # should change to whatever is selected in panel
        return self.execute(context)

def menu_func_mirror_changes(self, context):
    self.layout.operator(MirrorChanges.bl_idname)

# this is intended to be a copy paste of Mirror Changes, but has mask=True for the mirror changes function. This only exists so the mask button is its own button. TODO: find a way to make this call what it is copying, as that simplifies the code
# Mirror Changes As Mask --------------------------------------------------------------------
class MirrorChangesAsMask(bpy.types.Operator):
    """Texture Mirroring As Mask For Image Editor. Recommend using an inverting brush or a white brush set to exclusion on blending for masking.""" # tooltip for menu items and buttons
    bl_idname = "image.mirror_changes_as_mask" # unique identifier for menu items (cannot contain capitals)
    bl_label = "Mirror Changes As Mask" # display name
    bl_options = {'REGISTER', 'UNDO'} # Enables undo for the operator

    def execute(self, context): # function called when operation is run
        startTime = time.time()
        if (bpy.types.Scene.snapshotMapping is None or self.axis != bpy.types.Scene.snapshotMappingAxis): # if the mapping is none, then it is instantiated within the mirrorChanges function, so updating axis to account for this
            bpy.types.Scene.snapshotMappingAxis = self.axis
        MirrorChangesHelperFunction(self, context, True)
        if (timeDebug): # TIME
            print("MirrorChangesAsMask time: " + str(time.time() - startTime))
        return {'FINISHED'} # Tells blender the operation is done

    def invoke(self, context, axis): # function used to help add input into the above execute (is called by default when operator is called)
        self.axis = bpy.types.Scene.snapshotAxis # should change to whatever is selected in panel
        return self.execute(context)

def menu_func_mirror_changes_as_mask(self, context):
    self.layout.operator(MirrorChangesAsMask.bl_idname)

# Mirror 3D using baking -------------------------------------------------------------------
class MirrorChangesUsingBakingWithMask(bpy.types.Operator):
    """Texture Mirroring with mask using baking for Image Editor over selected axis. Recommend using an inverting brush or a white brush set to exclusion on blending for masking.""" # tooltip for menu items and buttons
    bl_idname = "image.mirror_changes_using_baking_with_mask" # unique identifier for menu items (cannot contain capitals)
    bl_label = "Mirror Changes Using Baking With Mask" # display name
    bl_options = {'REGISTER', 'UNDO'} # Enables undo for the operator

    def execute(self, context): # function called when operation is run
        startTime = time.time()
        myPointers = context.scene.snapshotObjectPointer

        for area in context.screen.areas:
            if area.type == 'IMAGE_EDITOR':
                image = area.spaces.active.image

        # sets selection to be the object in the UI
        bpy.ops.object.mode_set(mode='OBJECT')
        bpy.ops.object.select_all(action='DESELECT') # deselects every object
        myPointers.selectedObject.select_set(True) # selects the object
        bpy.context.view_layer.objects.active = myPointers.selectedObject # sets the object as active

        snapshotChanges = textureSnapshot(image) # snapshots it, storing it in a value
        image.pixels = bpy.types.Scene.snapshotOfOriginal.pixels # needs image to be like the snapshot for the baking parts to work, as they use images not snapshots
        snapshotUpdate = mirrorChangesFromSnapshotUsingBakingWithMask(bpy.types.Scene.snapshotOfOriginal, snapshotChanges, myPointers.selectedObject, image, bpy.types.Scene.snapshotAxis, myPointers.cageExtension, myPointers.selectedUV) # run method for performing baking of mirror where the texture is updated to only cover the parts marked with the mask
        image.pixels = snapshotUpdate.pixels # updates the textures pixels (very time expensive, so only done once at end)

        # make sure the original object is selected again
        myPointers.selectedObject.select_set(True) # selects the object
        bpy.context.view_layer.objects.active = myPointers.selectedObject # sets the object as active
        # makes sure the original image is selected again (necessary as the image generation of the function causes blender to view an empty image otherwise)
        for area in context.screen.areas:
            if area.type == 'IMAGE_EDITOR':
                area.spaces.active.image = image

        if (timeDebug): # TIME
            print("MirrorChangesUsingBakingWithMask time: " + str(time.time() - startTime))

        return {'FINISHED'} # Tells blender the operation is done

    def invoke(self, context, axis): # function used to help add input into the above execute (is called by default when operator is called)
        self.axis = bpy.types.Scene.snapshotAxis # should change to whatever is selected in panel
        return self.execute(context)

def menu_func_mirror_changes_using_baking_with_mask(self, context):
    self.layout.operator(MirrorChangesUsingBakingWithMask.bl_idname)

# Pixel Gap Fill ---------------------------------------------------------------------------
class PixelGapFill(bpy.types.Operator):
    """Fills in pixel sized gaps from mirroring""" # tooltip for menu items and buttons
    bl_idname = "image.pixel_gap_fill" # unique identifier for menu items (cannot contain capitals)
    bl_label = "Pixel Gap Fill" # display name
    bl_options = {'REGISTER', 'UNDO'} # Enables undo for the operator

    def execute(self, context): # function called when operation is run
        #grabs image
        for area in context.screen.areas:
            if area.type == 'IMAGE_EDITOR':
                image = area.spaces.active.image

        snapshotChanges = textureSnapshot(image)
        myPointers = context.scene.snapshotObjectPointer
        # TODO: add function or method that performs some sanity checks (should replace the checks in other functions with this as well), like whether the object is the same, whether the image is the same size, etc
        if (myPointers.pixelGapFillVerticalLines): # have call one of the pixel gap fills depending on whether the toggle is checked
            if (bpy.types.Scene.snapshotDiff != 0):
                pixelGapFill(bpy.types.Scene.snapshotDiff, snapshotChanges, selfBlend = myPointers.pixelGapFillSelfBlend)
        else:
            if (bpy.types.Scene.snapshotDiff != 0):
                pixelGapFillThreshold(bpy.types.Scene.snapshotDiff, snapshotChanges, threshold = myPointers.pixelGapFillThreshold, selfBlend = myPointers.pixelGapFillSelfBlend)
        image.pixels = snapshotChanges.pixels # updates the textures pixels (very time expensive, so only done once at end)
        return {'FINISHED'} # Tells blender the operation is done

    def invoke(self, context, axis): # function used to help add input into the above execute (is called by default when operator is called)
        return self.execute(context)

def menu_func_pixel_gap_fill(self, context):
    self.layout.operator(PixelGapFill.bl_idname)

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
        startTime = time.time()
        for area in context.screen.areas:
            if area.type == 'IMAGE_EDITOR':
                image = area.spaces.active.image
                #snapshotChanges = textureSnapshot(image)# snapshots it, storing it in a value
                if (bpy.types.Scene.snapshotObject == myPointers.selectedObject): # ensures the same object is for snapshots is still being used
                    # creates the bmesh of the object
                    if (myPointers.selectedObject.type == 'MESH'):
                        tempBmesh = bmesh.new()
                        tempBmesh.from_mesh(myPointers.selectedObject.data)
                        tempBmesh.faces.ensure_lookup_table()
                        bmesh.ops.triangulate(tempBmesh, faces=tempBmesh.faces, quad_method='BEAUTY', ngon_method='BEAUTY') # needs to be triangulated for the barymetric transformation
                        # creates the mapping and notes the axis used
                        bpy.types.Scene.snapshotMapping = createSnapshotMapping(object = myPointers.selectedObject, tempBmesh = tempBmesh, texture = image, snapshot = None, axis = self.axis, uv = myPointers.selectedUV, pixelMap = bpy.types.Scene.snapshotMapping) # makes a pixel map
                        bpy.types.Scene.snapshotMappingAxis = self.axis # updates what axis was used in the mapping
                        # frees the bmesh
                        tempBmesh.free()
                    else:
                        print("Error: Object selected is not a MESH object")
                else:
                    print("Error: Snapshot objects do not match")
        if (timeDebug): # TIME
            print("CreateMirrorMapping time: " + str(time.time() - startTime))
        return {'FINISHED'} # Tells blender the operation is done

    def invoke(self, context, axis): # function used to help add input into the above execute (is called by default when operator is called)
        self.axis = bpy.types.Scene.snapshotAxis # should change to whatever is selected in panel
        return self.execute(context)

def menu_func_mirror_changes(self, context):
    self.layout.operator(CreateMirrorMapping.bl_idname)

# Clear Mirror Mapping ---------------------------------------------------------------
class ClearMirrorMapping(bpy.types.Operator):
    """Clear Mirror Mapping For Image Editor""" # tooltip for menu items and buttons
    bl_idname = "image.clear_mirror_mapping" # unique identifier for menu items (cannot contain capitals)
    bl_label = "Clear Mirror Map" # display name
    bl_options = {'REGISTER', 'UNDO'} # Enables undo for the operator

    def execute(self, context): # function called when operation is run
        image = 0
        myPointers = context.scene.snapshotObjectPointer
        # grabs current selected image in image editor
        startTime = time.time()

        bpy.types.Scene.snapshotMapping = None # sets the mapping to None

        if (timeDebug): # TIME
            print("ClearMirrorMapping time: " + str(time.time() - startTime))
        return {'FINISHED'} # Tells blender the operation is done

    def invoke(self, context, axis): # function used to help add input into the above execute (is called by default when operator is called)
        self.axis = bpy.types.Scene.snapshotAxis # should change to whatever is selected in panel
        return self.execute(context)

def menu_func_mirror_changes(self, context):
    self.layout.operator(ClearMirrorMapping.bl_idname)

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

    faceSelectionMethodEnum : bpy.props.EnumProperty(
        name = "Face Selection Method",
        #description = "The method used for determining what faces to check in the 3D mirroring.",
        default = "All_Faces",
        items = [
            ('All_Faces', 'All Faces', 'Selects all faces the model/mesh has'),
            ('Edit_Mode_Selection', 'Edit Mode Selection', 'Selects the faces that are currently selected in the edit mode of the selected object. WARNING: The mirror map bypasses face selection intentionally to speed up the process. To prevent using it you can clear it with the Clear Mirror Map button.')], # enums are stored in the format (identifier, name, description) and this listing can be replaced with a function that passes a list of items in this format to make a dynamic enum property
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

    pixelGapFillVerticalLines : bpy.props.BoolProperty(
        name = "Pixel Gap Fill Vertical Lines",
        description = "Toggles whether pixel gap fill uses a threshold or simply fills in vertical gaps in the mirroring",
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

    cageExtension : bpy.props.FloatProperty(
        name = "Cage Extension",
        description = "The amount the object is extended for ray baking. Want really close to 0, but normally greater than 0 to help prevent z fighting.",
        default = 0.02,
        min = 0,
        max = 1,
    )

# Properties for the symmetry line -------------------------------------
class SymmetryLineProperties(bpy.types.PropertyGroup):
    enabled: bpy.props.BoolProperty(
        name="Enable Symmetry Line",
        default=False,
        description="Toggle symmetry line visibility"
    )
    color: bpy.props.FloatVectorProperty(
        name="Line Color",
        subtype='COLOR',
        default=(1.0, 0.2, 0.2, 0.8),
        size=4,
        min=0.0,
        max=1.0
    )
    line_thickness: bpy.props.IntProperty(
        name="Line Thickness",
        default=2,
        min=1,
        max=10 # TODO: see if can make this go over 10, as even if number is allowed larger than 10 it appears to stop rendering at 10 pixels thick
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
        symmetryLinePointers = context.scene.symmetry_line_props


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
        #b2row4.operator("image.draw_symmetry_line")
        # Controls
        b2row4.label(text = "-----Symmetry Line settings-----")
        b2row5 = box2.row()
        b2row5.prop(symmetryLinePointers, "enabled", text="Show Symmetry Line")
        b2row4.enabled = symmetryLinePointers.enabled
        b2row6 = box2.row()
        b2row6.prop(symmetryLinePointers, "color")
        b2row7 = box2.row()
        b2row7.prop(symmetryLinePointers, "line_thickness")

        # 3D Mirroring
        box3 = layout.box()
        box3.label(text = "Mirror 3D Settings")
        b3row1 = box3.row() # creates row in the box
        b3row1.operator("image.mirror_changes") # adds a button to the next row that is a button for its operator
        b3row2 = box3.row()
        b3row2.operator("image.mirror_changes_as_mask")
        b3row2_5 = box3.row()
        b3row2_5.prop(myPointers, "faceSelectionMethodEnum")
        b3row3 = box3.row()
        b3row3.operator("image.mirror_mapping")
        b3row3.operator("image.clear_mirror_mapping")
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
        b3row7 = box3.row()
        b3row7.operator("image.mirror_changes_using_baking_with_mask")
        b3row8 = box3.row()
        b3row8.prop(myPointers, "cageExtension")

        # Pixel Gap Fill
        box4 = layout.box()
        box4.operator("image.pixel_gap_fill")
        box4.label(text = "Pixel Gap Fill Settings")
        b4row1 = box4.row()
        b4row1.prop(myPointers, "pixelGapFillVerticalLines")
        b4row2 = box4.row()
        b4row2.prop(myPointers, "pixelGapFillThreshold")
        b4row3 = box4.row()
        b4row3.prop(myPointers, "pixelGapFillSelfBlend")

# Registering Addon ---------------------------------------------
handler_refs = [] # stores draw handler reference

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
    # clear mirror mapping
    bpy.utils.register_class(ClearMirrorMapping)
    # operators for panel help
    bpy.utils.register_class(ChooseXAxis)
    bpy.utils.register_class(ChooseYAxis)
    bpy.utils.register_class(ChooseZAxis)
    # mirror changes 2D
    bpy.utils.register_class(MirrorChanges2D)
    # mirror changes 2D as mask
    bpy.utils.register_class(MirrorChanges2DAsMask)
    # draw symmetry line
    #bpy.utils.register_class(DrawSymmetryLine)
    # mirror in 3d using baking
    bpy.utils.register_class(MirrorChangesUsingBakingWithMask)
    # pixel gap fill
    bpy.utils.register_class(PixelGapFill)
    # pointers class
    bpy.utils.register_class(MirrorAddonPointers)
    # symmetry line pointers class
    bpy.utils.register_class(SymmetryLineProperties)
    # panel
    bpy.utils.register_class(MirrorAddonPanel)
    # variables
    bpy.types.Scene.snapshotOfOriginal = textureSnapshot() # holds the snapshot
    bpy.types.Scene.snapshotDiff = 0 # holds what is changed for the pixel gap fill
    bpy.types.Scene.snapshotMapping = None # holds the mapping for a snapshot for one axis
    bpy.types.Scene.snapshotAxis = 'x' # the axis currently selected
    bpy.types.Scene.snapshotMappingAxis = None # axis used in making the mapping
    bpy.types.Scene.snapshotObject = None # holds the object the snapshot was made on
    bpy.types.Scene.snapshotObjectModifierPointUV = None
    bpy.types.Scene.snapshotObjectModifierPointModel = None
    bpy.types.Scene.snapshotObjectPointer = bpy.props.PointerProperty(type=MirrorAddonPointers)
    bpy.types.Scene.symmetry_line_props = bpy.props.PointerProperty(type=SymmetryLineProperties)

    # Register draw handler
    handler = bpy.types.SpaceImageEditor.draw_handler_add(
        draw_symmetry_line_callback, (), 'WINDOW', 'POST_PIXEL')
    handler_refs.append(handler)


def unregister():
    bpy.utils.unregister_class(SnapshotOriginal)
    bpy.utils.unregister_class(SnapshotRevert)
    bpy.utils.unregister_class(MirrorChanges)
    bpy.utils.unregister_class(MirrorChangesAsMask)
    bpy.utils.unregister_class(CreateMirrorMapping)
    bpy.utils.unregister_class(ClearMirrorMapping)
    bpy.utils.unregister_class(ChooseXAxis)
    bpy.utils.unregister_class(ChooseYAxis)
    bpy.utils.unregister_class(ChooseZAxis)
    bpy.utils.unregister_class(MirrorChanges2D)
    bpy.utils.unregister_class(MirrorChanges2DAsMask)
    #bpy.utils.unregister_class(DrawSymmetryLine)
    bpy.utils.unregister_class(MirrorChangesUsingBakingWithMask)
    bpy.utils.unregister_class(PixelGapFill)
    bpy.utils.unregister_class(MirrorAddonPointers)
    bpy.utils.unregister_class(SymmetryLineProperties)
    bpy.utils.unregister_class(MirrorAddonPanel)
    del bpy.types.Scene.snapshotOfOriginal
    del bpy.types.Scene.snapshotDiff
    del bpy.types.Scene.snapshotMapping
    del bpy.types.Scene.snapshotAxis
    del bpy.types.Scene.snapshotMappingAxis
    del bpy.types.Scene.snapshotObject
    del bpy.types.Scene.snapshotObjectModifierPointUV
    del bpy.types.Scene.snapshotObjectModifierPointModel
    del bpy.types.Scene.snapshotObjectPointer
    del bpy.types.Scene.symmetry_line_props

    # Remove draw handler
    for handler in handler_refs:
        bpy.types.SpaceImageEditor.draw_handler_remove(handler, 'WINDOW')
    handler_refs.clear()

# For testing addon by running in text editor
if __name__ == "__main__":
    register()
